#!/usr/bin/env python3
"""
In-process, section-keyed snapshot store for the :8001 service.

This is the single store behind GET /state. The health watcher and the fleet arbiter
each write their own named section of one shared instance. Neither overwrites the
other. /state reads the whole composite:

    store.set_section( "health_watcher", { ...health-watch view... } )
    store.set_section( "fleet_arbiter", { ...fleet snapshot... } )
    store.get()  ->  { "health_watcher": {...}, "fleet_arbiter": {...} }

The fleet arbiter writes through a sink adapter, so its own code is left untouched.

It never imports or calls `cosa.rest.arbiter_snapshot_store` (the in-process :7999
server singleton) and makes no outbound HTTP calls. The fleet-stall path therefore
works whether or not :7999 or :8000 is up. The :7999 reverse proxy pulls from
:8001/state; nothing here pushes to :7999.

The arbiter job's snapshot sink defaults to the :7999 singleton. On :8001 the fleet
arbiter's sink is pointed at this store's `fleet_arbiter` section. That keeps the
independence intact from end to end.
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
        - performs no file I/O and no network calls, so :8001 stays independent of :7999
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
