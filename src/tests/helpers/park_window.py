"""
Tell a park that bought no silence from one whose short window ran out before the read.
"""


def check_park_silence( count, elapsed, window ):
    """
    Fail with a message naming the cause when a freshly parked row is still counted as owed.

    Requires:
        - count is the owed count read straight after the park
        - elapsed is the seconds from setting the chase to finishing that read
        - window is the seconds the chase was set ahead

    Ensures:
        - returns None when count is 0
        - raises AssertionError naming a used-up window when elapsed is at least window
        - raises AssertionError saying the park bought no silence when elapsed is under window
    """
    if count == 0:
        return
    if elapsed >= window:
        raise AssertionError(
            f"WINDOW USED UP: the park and the first count took {elapsed:.1f} s of a {window} s "
            f"window, so the park had expired when the count ran (owed count {count}). "
            f"This is the test's timing, not a park that bought no silence." )
    raise AssertionError(
        f"park bought NO silence — owed count still {count}, read {elapsed:.1f} s into a "
        f"{window} s window" )
