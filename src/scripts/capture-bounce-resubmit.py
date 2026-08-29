#!/usr/bin/env python3
"""
Capture-bounce-resubmit control for the :8000 test-suite queue.

A bounce of the test container DESTROYS its in-memory todo queue: anything
queued at bounce time is silently lost, INCLUDING jobs owned by other people
(bug 2817b0f5, receipt 2026-08-15 — Cheech's and Mr. Radio's queued jobs both
vanished). The schedule-tests skill used to describe the remedy as a manual
procedure ("capture every queued job, bounce, resubmit them all"). A step that
depends on remembering is not a control, so this script IS the control.

What it does:
  1. Enumerate the :8000 pending (todo) queue.
  2. Save every pending job's reconstructed submit payload to a JSON file.
  3. Bounce the test container (refresh-test-server.sh).
  4. Resubmit every recoverable job — including jobs owned by someone else,
     since those are exactly the ones a human would forget.
  5. Report what it moved, what it could not, and where fidelity was lost.

FIDELITY LIMIT (stated loudly, never silently swallowed): the queue-listing API
(`GET /api/get-queue/todo`) exposes only `question_text`, `scheduled_at`, and
`monopolize` for a queued job. It does NOT expose `pytest_args`,
`auto_fix_on_failure`, or `env_vars`. Those fall back to server/INI defaults on
resubmit, and every affected job is flagged `fidelity_loss` in the report and
the capture file. A human can hand-patch from the saved capture file if a lost
override mattered.

WHAT THIS STILL LOSES (named plainly, because a tool whose job is "don't lose
queued jobs" must say what it still drops):
  - THE CAPTURE->BOUNCE RACE. Capture reads the todo queue at one instant; the
    bounce happens a moment later. Any job submitted in that gap is NOT in the
    capture, so it is destroyed by the bounce and never resubmitted. This
    script narrows the loss window from "the whole schedule-tests procedure" to
    "a few seconds," but it does not close it. A job submitted mid-run is still
    lost.
  - RUNNING-QUEUE JOBS ARE NOT CAPTURED. Only the pending (todo) queue is
    enumerated. A job already executing when the bounce lands is killed by the
    bounce and cannot be recovered here — a running job has no reconstructable
    submit payload, and resubmitting it would double-run work already partway
    done. Do not bounce while a job is running (the :8000 protocol already
    forbids it); this script does not make that safe.

Default mode is DRY-RUN (capture + report only, NO bounce, NO resubmit). Pass
`--apply` to actually bounce and resubmit.

Usage:
  # Safe: see what WOULD move, no bounce
  python src/scripts/capture-bounce-resubmit.py

  # Do it: capture -> bounce -> resubmit -> report
  python src/scripts/capture-bounce-resubmit.py --apply

  # Override target / capture path
  python src/scripts/capture-bounce-resubmit.py --apply \
      --base-url http://localhost:8000 --capture-file /tmp/cbr-capture.json

Env (same creds as smoke tests):
  LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL
  LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD
"""

import os
import sys
import json
import argparse
import subprocess
from datetime import datetime, timezone

# ── Bootstrap: this runs before cosa is importable, so set sys.path manually ──
_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root is None:
    # Fall back to walking up from this file's location (src/scripts/ -> root).
    _lupin_root = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", ".." ) )
_src_path = os.path.join( _lupin_root, "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

# stdlib-only for HTTP so the script has no third-party dependency on the host.
import urllib.request
import urllib.error


# ═══════════════════════════════════════════════════════════════════════════════
# Pure reconstruction logic (no I/O — unit-tested directly)
# ═══════════════════════════════════════════════════════════════════════════════

# The queue-listing API does not surface these submit fields for a queued job.
# They fall back to server/INI defaults on resubmit; we flag them so the loss is
# visible, never silent.
FIDELITY_LOST_FIELDS = [ "pytest_args", "auto_fix_on_failure", "env_vars" ]

# TestSuiteJob.last_question_asked renders as "[Tests] integration, e2e".
_TESTS_PREFIX = "[Tests] "


def parse_test_types( question_text ):
    """
    Recover the test_types list from a queued test-suite job's display string.

    Requires:
        - question_text is a string or None

    Ensures:
        - returns a non-empty list[str] of stripped suite names when
          question_text matches the "[Tests] a, b" render
        - returns None when question_text is None, not a str, or does not
          match the test-suite render (i.e. not a reconstructable test job)

    Raises:
        - nothing
    """
    if not isinstance( question_text, str ):
        return None
    if not question_text.startswith( _TESTS_PREFIX ):
        return None
    remainder = question_text[ len( _TESTS_PREFIX ): ].strip()
    if not remainder:
        return None
    suites = [ s.strip() for s in remainder.split( "," ) if s.strip() ]
    return suites or None


def build_capture_record( job_meta ):
    """
    Turn one raw todo-queue metadata dict into a capture record.

    Requires:
        - job_meta is a dict from `todo_jobs_metadata` (has at least job_id,
          question_text, agent_type keys; missing keys are tolerated)

    Ensures:
        - returns a dict with keys: job_id, agent_type, owner_email,
          question_text, scheduled_at, resubmittable (bool), reason (str),
          payload (dict or None), fidelity_loss (list[str])
        - resubmittable is True ONLY when a test-suite payload could be rebuilt
        - owner jobs (any owner_email) are ALWAYS captured — never filtered out
        - payload, when present, is a POST /api/test-suite/submit body

    Raises:
        - nothing
    """
    job_id        = job_meta.get( "job_id" )
    agent_type    = job_meta.get( "agent_type" )
    owner_email   = job_meta.get( "user_email" )
    question_text = job_meta.get( "question_text" )
    scheduled_at  = job_meta.get( "scheduled_at" )

    record = {
        "job_id"        : job_id,
        "agent_type"    : agent_type,
        "owner_email"   : owner_email,
        "question_text" : question_text,
        "scheduled_at"  : scheduled_at,
        "resubmittable" : False,
        "reason"        : "",
        "payload"       : None,
        "fidelity_loss" : [],
    }

    test_types = parse_test_types( question_text )
    if test_types is None:
        record[ "reason" ] = (
            f"no resubmit path for agent_type={agent_type!r} "
            f"(only test-suite jobs are reconstructable from the queue API) "
            f"— saved to capture file for manual handling"
        )
        return record

    # Reconstructable test-suite job. monopolize is always True from the
    # constructor, and the submit endpoint forces it too, so we don't carry it.
    payload = { "test_types": ",".join( test_types ) }
    if scheduled_at:
        payload[ "scheduled_at" ] = scheduled_at

    record[ "resubmittable" ] = True
    record[ "payload" ]       = payload
    record[ "fidelity_loss" ] = list( FIDELITY_LOST_FIELDS )
    record[ "reason" ]        = "test-suite job reconstructed from queue metadata"
    return record


# ═══════════════════════════════════════════════════════════════════════════════
# Queue client (thin urllib wrapper — injected as a fake in tests)
# ═══════════════════════════════════════════════════════════════════════════════

class QueueClient:
    """HTTP client for the Lupin queue + test-suite endpoints."""

    def __init__( self, base_url, token=None, timeout=15 ):
        """
        Requires:
            - base_url is a non-empty URL string (no trailing slash needed)

        Ensures:
            - stores base_url, token, timeout for subsequent calls
        """
        self.base_url = base_url.rstrip( "/" )
        self.token    = token
        self.timeout  = timeout

    def _request( self, method, path, body=None, auth=True ):
        """Issue a JSON request and return the decoded JSON response."""
        url     = f"{self.base_url}{path}"
        data    = json.dumps( body ).encode() if body is not None else None
        headers = { "Content-Type": "application/json" }
        if auth and self.token:
            headers[ "Authorization" ] = f"Bearer {self.token}"
        req = urllib.request.Request( url, data=data, headers=headers, method=method )
        with urllib.request.urlopen( req, timeout=self.timeout ) as resp:
            return json.loads( resp.read().decode() )

    def login( self, email, password ):
        """
        Authenticate and cache the access token.

        Requires:
            - email and password are non-empty strings

        Ensures:
            - self.token is set to the returned access token
            - returns the access token string
        """
        resp = self._request(
            "POST", "/auth/login",
            body={ "email": email, "password": password }, auth=False
        )
        self.token = resp[ "tokens" ][ "access_token" ]
        return self.token

    def fetch_todo( self ):
        """
        Return the list of pending (todo) job metadata dicts.

        Ensures:
            - returns the `todo_jobs_metadata` list (possibly empty)
        """
        resp = self._request( "GET", "/api/get-queue/todo" )
        return resp.get( "todo_jobs_metadata", [] )

    def submit( self, payload ):
        """
        Submit one test-suite job; return the decoded response JSON.

        Requires:
            - payload is a POST /api/test-suite/submit body dict
        """
        return self._request( "POST", "/api/test-suite/submit", body=payload )


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestration (client + bouncer injected — unit-tested with fakes)
# ═══════════════════════════════════════════════════════════════════════════════

def capture( client ):
    """
    Enumerate the pending queue and build a capture record per job.

    Requires:
        - client exposes fetch_todo() -> list[dict]

    Ensures:
        - returns a list of capture records, ONE PER pending job, in queue order
        - jobs owned by other people are included (never filtered by owner)
    """
    records = []
    for job_meta in client.fetch_todo():
        records.append( build_capture_record( job_meta ) )
    return records


def save_capture( records, path ):
    """
    Persist the capture records to a JSON file.

    Requires:
        - records is a list of capture-record dicts
        - path is a writable filesystem path

    Ensures:
        - writes a JSON document {captured_at, count, records} to path
        - returns path
    """
    doc = {
        "captured_at" : datetime.now( timezone.utc ).isoformat(),
        "count"       : len( records ),
        "records"     : records,
    }
    with open( path, "w" ) as fh:
        json.dump( doc, fh, indent=2 )
    return path


def resubmit( client, records ):
    """
    Resubmit every resubmittable record — including other owners' jobs.

    Requires:
        - client exposes submit(payload) -> dict (with a 'job_id' on success)
        - records is a list of capture records from capture()

    Ensures:
        - calls client.submit() once for EACH record where resubmittable is True
        - never skips a record on the basis of its owner_email
        - annotates each record in place with resubmit_status ('moved' |
          'failed' | 'skipped') and, on success, new_job_id
        - returns the same records list

    Raises:
        - nothing (per-job submit failures are captured on the record)
    """
    for record in records:
        if not record[ "resubmittable" ]:
            record[ "resubmit_status" ] = "skipped"
            record[ "new_job_id" ]      = None
            continue
        try:
            resp = client.submit( record[ "payload" ] )
            record[ "resubmit_status" ] = "moved"
            record[ "new_job_id" ]      = resp.get( "job_id" )
        except Exception as e:  # noqa: BLE001 — surfaced per-job, run continues
            record[ "resubmit_status" ] = "failed"
            record[ "new_job_id" ]      = None
            record[ "resubmit_error" ]  = str( e )
    return records


def run_capture_bounce_resubmit( client, bouncer, capture_path, apply=False ):
    """
    Full control: capture -> save -> (bounce -> resubmit if apply) -> report.

    Requires:
        - client exposes fetch_todo() and submit()
        - bouncer is a zero-arg callable that bounces the test container
        - capture_path is a writable path for the capture JSON

    Ensures:
        - the capture file is ALWAYS written (dry-run and apply alike)
        - in apply mode, bouncer() is called AFTER capture and BEFORE resubmit —
          resubmitting against the pre-bounce (stale-code) server would defeat
          the whole purpose
        - in dry-run mode, bouncer() is NOT called and no job is resubmitted
        - returns a report dict:
          {apply, capture_path, total, resubmittable, moved, failed,
           unrecoverable, fidelity_loss_jobs, records}

    Raises:
        - nothing from capture/resubmit; a bounce failure propagates (an
          un-bounced server means the resubmit half must NOT run)
    """
    records = capture( client )
    save_capture( records, capture_path )

    if apply:
        bouncer()                       # ORDER MATTERS: bounce before resubmit
        resubmit( client, records )

    resubmittable = [ r for r in records if r[ "resubmittable" ] ]
    moved         = [ r for r in records if r.get( "resubmit_status" ) == "moved" ]
    failed        = [ r for r in records if r.get( "resubmit_status" ) == "failed" ]
    unrecoverable = [ r for r in records if not r[ "resubmittable" ] ]
    fidelity_jobs = [ r for r in records if r[ "fidelity_loss" ] ]

    return {
        "apply"              : apply,
        "capture_path"       : capture_path,
        "total"              : len( records ),
        "resubmittable"      : len( resubmittable ),
        "moved"              : len( moved ),
        "failed"             : len( failed ),
        "unrecoverable"      : len( unrecoverable ),
        "fidelity_loss_jobs" : len( fidelity_jobs ),
        "records"            : records,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Reporting + host wiring
# ═══════════════════════════════════════════════════════════════════════════════

def format_report( report ):
    """
    Render a human-readable text report from run_capture_bounce_resubmit().

    Requires:
        - report is the dict returned by run_capture_bounce_resubmit

    Ensures:
        - returns a multi-line string; every captured job appears exactly once
        - other-owner jobs are labelled so a human sees what was moved on their
          behalf
    """
    mode  = "APPLY (bounced + resubmitted)" if report[ "apply" ] else "DRY-RUN (no bounce, no resubmit)"
    lines = []
    lines.append( "=" * 78 )
    lines.append( f"Capture-bounce-resubmit :8000  —  {mode}" )
    lines.append( "=" * 78 )
    lines.append(
        f"captured={report['total']}  resubmittable={report['resubmittable']}  "
        f"moved={report['moved']}  failed={report['failed']}  "
        f"unrecoverable={report['unrecoverable']}  "
        f"fidelity_loss={report['fidelity_loss_jobs']}"
    )
    lines.append( f"capture file: {report['capture_path']}" )
    lines.append( "-" * 78 )
    for r in report[ "records" ]:
        status = r.get( "resubmit_status", "captured" )
        owner  = r.get( "owner_email" ) or "?"
        newid  = r.get( "new_job_id" )
        tail   = f" -> {newid}" if newid else ""
        floss  = "  [FIDELITY-LOSS: " + ",".join( r[ "fidelity_loss" ] ) + "]" if r[ "fidelity_loss" ] else ""
        lines.append( f"  [{status:11}] {r.get('question_text') or r.get('agent_type')}  (owner={owner}){tail}{floss}" )
        if r.get( "resubmit_status" ) == "failed":
            lines.append( f"               ! resubmit error: {r.get( 'resubmit_error' )}" )
        if not r[ "resubmittable" ]:
            lines.append( f"               ! {r[ 'reason' ]}" )
    lines.append( "=" * 78 )
    if report[ "fidelity_loss_jobs" ]:
        lines.append(
            "NOTE: the queue API does not expose pytest_args / auto_fix_on_failure / "
            "env_vars; those reverted to defaults on resubmit. Hand-patch from the "
            "capture file if a lost override mattered."
        )
    return "\n".join( lines )


def _make_host_bouncer( quiet=False ):
    """Return a bouncer callable that runs refresh-test-server.sh on the host."""
    script = os.path.join( _lupin_root, "src", "scripts", "refresh-test-server.sh" )

    def _bounce():
        cmd = [ script ] + ( [ "--quiet" ] if quiet else [] )
        subprocess.run( cmd, check=True )

    return _bounce


def _default_capture_path():
    """Timestamp-free default so the same run's file is deterministic per pid."""
    return os.path.join( "/tmp", f"cbr-capture-{os.getpid()}.json" )


def main( argv=None ):
    """
    CLI entry point.

    Ensures:
        - dry-run by default (capture + report only)
        - --apply performs bounce + resubmit
        - returns process exit code (0 ok, 2 on missing creds, 1 on bounce fail)
    """
    parser = argparse.ArgumentParser( description="Capture-bounce-resubmit the :8000 test queue." )
    parser.add_argument( "--apply", action="store_true", help="Actually bounce + resubmit (default: dry-run)" )
    parser.add_argument( "--base-url", default=os.environ.get( "LUPIN_SCHEDULE_BASE_URL", "http://localhost:8000" ) )
    parser.add_argument( "--capture-file", default=None, help="Where to save captured payloads (default: /tmp/cbr-capture-<pid>.json)" )
    parser.add_argument( "--quiet", action="store_true", help="Quieter bounce output" )
    args = parser.parse_args( argv )

    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        print(
            "ERROR: set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and "
            "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD before running.",
            file=sys.stderr,
        )
        return 2

    capture_path = args.capture_file or _default_capture_path()

    client = QueueClient( args.base_url )
    client.login( email, password )

    try:
        report = run_capture_bounce_resubmit(
            client       = client,
            bouncer      = _make_host_bouncer( quiet=args.quiet ),
            capture_path = capture_path,
            apply        = args.apply,
        )
    except subprocess.CalledProcessError as e:
        print( f"ERROR: bounce failed ({e}); capture file saved at {capture_path}, no resubmit performed.", file=sys.stderr )
        return 1

    print( format_report( report ) )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
