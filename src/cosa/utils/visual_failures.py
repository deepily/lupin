#!/usr/bin/env python3
"""
Run-scoped home for visual-snapshot failure PNGs (row d51ffc36).

The stock pytest-playwright-visual-snapshot plugin deletes one shared folder at the start of
EVERY pytest session that loads it, unit sessions included, so a routine unit run destroyed the
last E2E run's actual/expected PNGs (measured 2026-09-30: emptied at 16:27:59 by a unit run, 28
minutes after e2e_b finished). This module holds the two decisions that stop that:

    - a session only touches the failures area when it collects a visual-snapshot test
    - each such session writes to its OWN run directory (named by the ts- job id when there is
      one) and never deletes a run directory it is not pruning for age
"""

import os
import shutil
import time
from datetime import datetime, timezone

RUN_ID_ENV        = "LUPIN_TEST_RUN_ID"
JOB_ID_ENV        = "LUPIN_TEST_SUITE_JOB_ID"    # exported by TestSuiteJob: "ts-<8 hex>"
SNAPSHOT_FIXTURE  = "assert_snapshot"
KEEP_DAYS_DEFAULT = 14
KEEP_NEWEST       = 5


def make_run_id( environ=None, now=None, pid=None ):
    """
    Requires:
        - environ is a mapping or None (None reads os.environ)

    Ensures:
        - returns $LUPIN_TEST_RUN_ID when set and non-blank (an explicit override)
        - otherwise the test-suite job id $LUPIN_TEST_SUITE_JOB_ID ("ts-..."), so a row can cite
          the folder by the job it came from
        - otherwise returns "<UTC yyyymmddThhmmssZ>-<pid>", unique per process and second
    """
    environ = os.environ if environ is None else environ
    for key in ( RUN_ID_ENV, JOB_ID_ENV ):
        given = environ.get( key, "" ).strip()
        if given: return given
    now = datetime.now( timezone.utc ) if now is None else now
    pid = os.getpid() if pid is None else pid
    return f"{now.strftime( '%Y%m%dT%H%M%SZ' )}-{pid}"


def session_collects_visual( items ):
    """
    Requires:
        - items is an iterable of pytest items (anything with .fixturenames)

    Ensures:
        - True iff at least one item requests a fixture named assert_snapshot*
          (the stock one or any of this repo's tolerant variants)
    """
    return any( name.startswith( SNAPSHOT_FIXTURE )
                for item in items for name in item.fixturenames )


def prepare_run_dir( base, run_id, keep_days=KEEP_DAYS_DEFAULT, keep_newest=KEEP_NEWEST, now=None ):
    """
    Requires:
        - base is a directory path (created if absent), run_id is a plain name (no separators)

    Ensures:
        - returns base/run_id, created if absent and NEVER deleted or emptied: a job that runs
          two pytest sessions (e2e_a then e2e_b) shares one folder, and the second must not
          destroy the first's evidence
        - sibling DIRECTORIES are pruned only when they are older than keep_days AND not among
          the keep_newest most recently modified; the current run's folder is never a candidate
        - files directly under base, and every younger or newest-N directory, are left as they were
    Raises:
        - ValueError if run_id contains a path separator or is "" / "." / ".."
    """
    if os.sep in run_id or ( os.altsep and os.altsep in run_id ) or run_id in ( "", ".", ".." ):
        raise ValueError( f"run_id must be a plain directory name, got {run_id!r}" )

    now = time.time() if now is None else now
    os.makedirs( base, exist_ok=True )
    others = sorted( ( e for e in os.scandir( base ) if e.is_dir( follow_symlinks=False ) and e.name != run_id ),
                     key=lambda e: e.stat().st_mtime, reverse=True )
    cutoff = now - keep_days * 86400
    for entry in others[ keep_newest: ]:
        if entry.stat().st_mtime < cutoff:
            shutil.rmtree( entry.path, ignore_errors=True )

    run_dir = os.path.join( base, run_id )
    os.makedirs( run_dir, exist_ok=True )
    return run_dir
