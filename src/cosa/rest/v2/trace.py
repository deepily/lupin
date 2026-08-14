"""StageTrace — a multi-mark, per-request tracer for CJ Flow v2.

The whole question of whether the v2 control logic is fast enough turns on
*which* stage dominates, so a single ``t_cache_lookup`` would hide the answer.
StageTrace records a monotonic ``perf_counter_ns()`` mark per named stage plus
arbitrary metadata fields (``path``, ``route_reason``, ``best_score``,
``id_hash`` on write-back, …), then emits one JSONL record — the authoritative
metric source (``io/v2-flow/trace-YYYY-MM-DD.jsonl``).

Design notes:
    - The clock is injectable so tests are deterministic (no wall-clock reads).
    - Container values handed to ``set()`` are copied at the boundary — v2's
      standing rule is that no dict/list leaves or enters a shared structure by
      reference, so a caller's later mutation can never rewrite a recorded field.
    - Nothing here imports heavy machinery; the module depends only on stdlib
      plus ``cosa.utils.util`` for the project-root path.
"""

from __future__ import annotations

import copy
import json
import os
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import cosa.utils.util as du


class StageTrace:
    """One request's stage marks + fields, emittable as a single JSONL record.

    Requires:
        - clock is a zero-arg callable returning a monotonically increasing int
          of nanoseconds (defaults to time.perf_counter_ns).

    Ensures:
        - mark() records the clock value for a named stage (last write wins).
        - set() records a metadata field, copying dict/list/set values so no
          shared reference is retained.
        - timings_ms() reports each mark's millisecond offset from the anchor.
        - write() appends one JSON line to the day's trace file and returns its
          path.
    """

    def __init__(
        self,
        trace_id  : Optional[ str ]           = None,
        trace_dir : Optional[ str ]           = None,
        anchor    : str                       = "t_recv",
        clock     : Callable[ [], int ]       = time.perf_counter_ns,
    ) -> None:
        self.trace_id  = trace_id if trace_id is not None else uuid.uuid4().hex
        self.trace_dir = trace_dir if trace_dir is not None else du.get_project_root() + "/io/v2-flow"
        self.anchor    = anchor
        self._clock    = clock
        self._marks    : Dict[ str, int ] = {}
        self.fields    : Dict[ str, Any ] = {}

    def mark( self, name: str ) -> int:
        """
        Record the current clock value for stage `name`.

        Requires:
            - name is a non-empty string.

        Ensures:
            - self._marks[name] holds the clock reading (last write wins).
            - returns that reading.
        """
        value            = self._clock()
        self._marks[ name ] = value
        return value

    def has_mark( self, name: str ) -> bool:
        """Return True iff stage `name` has been marked."""
        return name in self._marks

    def set( self, key: str, value: Any ) -> None:
        """
        Record a metadata field, copying containers at the boundary.

        Requires:
            - key is a non-empty string.

        Ensures:
            - self.fields[key] holds value; dict/list/set values are shallow
              copied so a later mutation by the caller cannot rewrite the record.
        """
        if isinstance( value, ( dict, list, set ) ):
            self.fields[ key ] = copy.copy( value )
        else:
            self.fields[ key ] = value

    def update( self, **fields: Any ) -> None:
        """Record several metadata fields at once via repeated set()."""
        for key, value in fields.items():
            self.set( key, value )

    def elapsed_ms( self, start: str, end: str ) -> Optional[ float ]:
        """
        Milliseconds between two marks, or None if either is absent.

        Requires:
            - start and end name stages that may or may not have been marked.

        Ensures:
            - returns (marks[end] - marks[start]) / 1e6 rounded to 3 places when
              both exist, else None.
        """
        if start not in self._marks or end not in self._marks:
            return None
        return round( ( self._marks[ end ] - self._marks[ start ] ) / 1_000_000, 3 )

    def timings_ms( self ) -> Dict[ str, float ]:
        """
        Each mark's millisecond offset from the anchor.

        Ensures:
            - returns {} when no marks exist.
            - anchor is self.anchor when marked, otherwise the earliest mark.
            - every offset is rounded to 3 places.
        """
        if not self._marks:
            return {}
        if self.anchor in self._marks:
            base = self._marks[ self.anchor ]
        else:
            base = min( self._marks.values() )
        return { name: round( ( value - base ) / 1_000_000, 3 ) for name, value in self._marks.items() }

    def to_record( self ) -> Dict[ str, Any ]:
        """
        Assemble the full JSONL record for this trace.

        Ensures:
            - returns a dict carrying trace_id, an ISO wall-clock timestamp,
              timings_ms, and a copy of every recorded field.
        """
        record = {
            "trace_id"   : self.trace_id,
            "ts"         : datetime.now().isoformat(),
            "timings_ms" : self.timings_ms(),
        }
        record.update( copy.copy( self.fields ) )
        return record

    def write( self, today: Optional[ str ] = None ) -> str:
        """
        Append one JSON line to the day's trace file.

        Requires:
            - self.trace_dir is a writable directory path (created if absent).

        Ensures:
            - a file trace-YYYY-MM-DD.jsonl gains exactly one line: to_record().
            - returns the path written.
        """
        day  = today if today is not None else datetime.now().strftime( "%Y-%m-%d" )
        os.makedirs( self.trace_dir, exist_ok=True )
        path = os.path.join( self.trace_dir, f"trace-{day}.jsonl" )
        with open( path, "a" ) as handle:
            handle.write( json.dumps( self.to_record() ) + "\n" )
        return path
