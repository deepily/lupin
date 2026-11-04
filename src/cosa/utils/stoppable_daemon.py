"""
The start and stop of a polling daemon thread.

A class that owns a `threading.Event` named `_stop_event` and a `threading.Thread` named
`_thread` (None until started) takes its start() and stop() from this mixin. The standalone
arbiter imports this module, so it uses the standard library only.
"""

import threading


class StoppableDaemonMixin:
    """
    Gives a daemon-loop class a start() that spawns its thread and a stop() that joins it.

    Requires:
        - the class sets THREAD_NAME to the thread's name
        - the class defines _enabled() -> bool and _loop() -> None
        - a class whose gate is more than _enabled() overrides _should_start()
    """

    THREAD_NAME: str

    def _should_start( self ) -> bool:
        """Return whether the rollout flag lets the thread start (the class's _enabled() by default)."""
        return self._enabled()

    def start( self ) -> bool:
        """
        Spawn the daemon thread, only if the flag is on and no thread runs.

        Returns True if a thread was started, else False. That is the no-op
        rollout gate: a disabled class never spawns.
        """
        if not self._should_start():
            return False
        if self._thread is not None and self._thread.is_alive():
            return False
        self._stop_event.clear()
        self._thread = threading.Thread( target=self._loop, daemon=True, name=self.THREAD_NAME )
        self._thread.start()
        return True

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
