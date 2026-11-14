"""
The two planning-is-prompting ticks in the job registry run on the host.

Rick ruled "Host via job runner" for both.

- context-tick runs on the host through cron-job.sh with its command on the cron line, so its registry entry has no
  run block, and the Background Jobs page offers no Run now button the container could never carry out.
- doc-parity-tick is scheduled for 07:30, when the host is usually off, so it also runs after boot.
"""
import json
import os
from pathlib import Path

ROOT     = Path( os.environ[ "LUPIN_ROOT" ] )
REGISTRY = ROOT / "src" / "conf" / "job-registry.json"


def entry( job ):
    """
    Requires:
        - job names a job in the registry
    Ensures:
        - returns that job's registry entry
    """
    jobs = json.loads( REGISTRY.read_text( encoding="utf-8" ) )[ "jobs" ]
    return next( j for j in jobs if j[ "job" ] == job )


def test_the_context_tick_has_no_run_block_so_no_run_now_button():
    assert "run" not in entry( "context-tick" )


def test_the_context_tick_is_still_scheduled_and_left_to_its_own_installer():
    ent = entry( "context-tick" )
    assert ent[ "schedule" ] == [ { "cron": "9,19,29,39,49,59 * * * *" } ]
    assert "cron-job.sh context-tick cron" in ent[ "cron_exclusion_reason" ]


def test_the_doc_parity_tick_also_runs_after_boot():
    schedule = entry( "doc-parity-tick" )[ "schedule" ]
    assert { "cron": "30 7 * * *" } in schedule
    assert { "after_boot_seconds": 180 } in schedule


def test_the_doc_parity_tick_keeps_its_run_block_because_cron_job_sh_reads_it():
    assert entry( "doc-parity-tick" )[ "run" ][ "argv" ] == [ "{pip}/workflow/scripts/doc-parity-tick.sh" ]
