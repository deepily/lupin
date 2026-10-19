"""
The stop half of a polling daemon thread.

A class that owns a `threading.Event` named `_stop_event` and a `threading.Thread` named
`_thread` (None until started) takes its stop() from this mixin.
"""


class StoppableDaemonMixin:
    """Gives a daemon-loop class a stop() that signals the loop and joins its thread."""

    def stop( self, timeout: float = 5.0 ) -> None:
        """
        Signal the daemon to exit and join it.

        Requires:
            - self._stop_event is a threading.Event
            - self._thread is a threading.Thread, or None when never started
            - timeout is a number of seconds

        Ensures:
            - the stop event is set
            - a live thread is joined for at most `timeout` seconds
            - idempotent: safe if never started and safe to call twice
        """
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join( timeout=timeout )
