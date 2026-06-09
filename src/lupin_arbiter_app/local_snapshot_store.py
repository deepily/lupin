#!/usr/bin/env python3
"""
:8001-LOCAL, SECTION-KEYED in-process snapshot store — the R4 independence linchpin.

The single coherent store behind GET /state (L4). The health watcher (L2) and the
fleet arbiter (L3) each write their OWN named SECTION of one shared instance — no
clobber — and /state reads the whole composite:

    store.set_section( "health_watcher", { ...health-watch view... } )  # health watcher (L2)
    store.set_section( "fleet_arbiter", { ...fleet snapshot... } )      # fleet arbiter (L3, via a
                                                                        # sink-adapter — the
                                                                        # v2.2 arbiter code is
                                                                        # left untouched)
    store.get()  ->  { "health_watcher": {...}, "fleet_arbiter": {...} }  # /state (L4)

It deliberately does NOT import or call `cosa.rest.arbiter_snapshot_store` (the
in-process :7999 server singleton) and makes ZERO outbound HTTP — so the
fleet-stall path has no dependency on :7999/:8000 being up (deploy doc R4). The
:7999 reverse-proxy (R3) PULLS from :8001/state; nothing here pushes to :7999.

This closes the snapshot-sink trap Tiffany (B1 reviewer) flagged pre-build and
Tiberius ratified: the v2.1 arbiter_job._snapshot_sink DEFAULTS to the :7999
singleton (arbiter_job.py:53,217,339); on :8001 we point the fleet arbiter's sink at this
store's `fleet_arbiter` section so the independence invariant holds end-to-end.
"""
import threading
from typing import Any, Dict, Optional


class LocalSnapshotStore:
    """
    Thread-safe, in-process, section-keyed holder for the :8001 service state.

    Requires:
        - section values passed to set_section() are JSON-serialisable

    Ensures:
        - set_section( name, value ) stores `value` under `name` (overwrites that
          section only — other sections untouched, so multiple loop writers never
          clobber each other)
        - get_section( name ) returns that section's value, or None if unset
        - get() returns a shallow copy of the whole composite {section: value}
        - concurrent writes (loop threads) and reads (the /state handler) are
          serialised by an internal lock
        - performs NO file I/O and NO network calls (R4 independence)
    """

    def __init__( self ) -> None:
        self._lock     = threading.Lock()
        self._sections : Dict[ str, Any ] = { }

    def set_section( self, name: str, value: Any ) -> None:
        """Ensures: stores `value` under section `name` (overwrites that section only)."""
        with self._lock:
            self._sections[ name ] = value

    def get_section( self, name: str ) -> Optional[ Any ]:
        """Ensures: returns the value stored under `name`, or None if unset."""
        with self._lock:
            return self._sections.get( name )

    def get( self ) -> Dict[ str, Any ]:
        """Ensures: returns a shallow copy of the whole composite {section: value}."""
        with self._lock:
            return dict( self._sections )

    def clear( self ) -> None:
        """Ensures: drops all sections back to empty."""
        with self._lock:
            self._sections.clear()
