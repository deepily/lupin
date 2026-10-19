"""
The guarded poll loop shared by the arbiter service's two observers.

The context-pressure writer and the health watcher each tick on a thread: poll, then sleep.
One bad poll must never end the loop, because an observer that stops observing is a silent
failure. The loop lives here once. It imports only the standard library, so the light venv of
the :8001 service needs nothing new.
"""


def run_poll_loop( stop, poll_once, log_fn, clock, interval_seconds ):
    """
    Poll until stop is set, logging any error a poll raises and sleeping between polls.

    Requires:
        - stop has is_set(), as a threading.Event does
        - poll_once is called with no arguments
        - log_fn( event, **fields ) records a structured event
        - clock has sleep( seconds )
        - interval_seconds is the pause after each poll

    Ensures:
        - poll_once runs at least once unless stop is already set
        - a poll that raises is logged as "poll_error" with the error text, and the loop goes on
        - clock.sleep( interval_seconds ) runs after every poll, including one that raised
        - returns only when stop is set

    Raises:
        - nothing from poll_once; errors from log_fn or clock.sleep are not caught
    """
    while not stop.is_set():
        try:
            poll_once()
        except Exception as e:
            log_fn( "poll_error", error=str( e ) )
        clock.sleep( interval_seconds )
