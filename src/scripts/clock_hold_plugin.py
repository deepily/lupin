"""
pytest plugin: hold the session open for a fixed interval, changing nothing else.

Row `87ae7234`. This is the DEMONSTRATION lever, not the detector. Held beside an
otherwise-identical baseline it shows the defect plainly - the same 333 tests report
15% or 18% of session_bridge.py depending only on session length. It was tried as a
detector and rejected: it fires only when the baseline finishes inside one poll
interval, and under subprocess overhead the baseline took 5.6s against a 2.0s poll,
reporting CLEAN on a scope it had itself proven dirty. The shipped detector is
`detect_thread_credited_coverage.py`, which uses thread attribution instead. Background threads accrue coverage while the
session is open, so any line covered in the held run and not in the baseline was
credited by elapsed time rather than by a test.

Interval comes from LUPIN_CLOCK_HOLD_SECONDS (default 12.0), which must exceed the
slowest poll interval among the threads under test — cosa_voice_mcp's watcher polls
every 2.0s.
"""
import os
import time


def pytest_collection_finish( session ):
    hold = float( os.environ.get( "LUPIN_CLOCK_HOLD_SECONDS", "12.0" ) )
    if hold > 0: time.sleep( hold )
