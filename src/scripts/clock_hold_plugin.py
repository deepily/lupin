"""
pytest plugin: hold the session open for a fixed interval, changing nothing else.

This is the demonstration lever, not the detector. The shipped detector is `detect_thread_credited_coverage.py`.

Notes:
    - Held beside an otherwise-identical baseline, it shows the defect plainly.
    - The same 333 tests report 15% or 18% of session_bridge.py depending only on session length.
    - Background threads accrue coverage while the session is open.
    - So any line covered in the held run and not in the baseline was credited by elapsed time, not by a test.
    - It was tried as a detector and rejected, because it fires only when the baseline finishes inside one poll interval.
    - Under subprocess overhead the baseline took 5.6s against a 2.0s poll.
    - It then reported clean on a scope it had itself proven dirty.
    - The shipped detector uses thread attribution instead.
    - The interval comes from `LUPIN_CLOCK_HOLD_SECONDS` (default 12.0).
    - It must exceed the slowest poll interval among the threads under test.
    - The watcher in cosa_voice_mcp polls every 2.0s.
"""
import os
import time


def pytest_collection_finish( session ):
    hold = float( os.environ.get( "LUPIN_CLOCK_HOLD_SECONDS", "12.0" ) )
    if hold > 0: time.sleep( hold )
