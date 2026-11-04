"""
PendingRequests: parked v2 flows awaiting a human's missing argument.

The router may get the intent while a required argument is still missing after the phi4 extraction
pass. The v2 endpoint then does not block. It parks the request and returns the first question
immediately. It runs the human round-trip on a background thread. This module holds those parked
requests.

Two properties matter and are enforced here rather than left to callers:

    1. Bounded growth. An in-process dict that only ever grows leaks memory across a long eval run.
       Every entry carries a creation time. sweep() and every get() drop entries older than the TTL.

    2. An AI-observable completion seam. The resume thread's only real-world output is TTS to a
       human, which the AI cannot hear. So each entry has a pollable `status` that the resume thread
       advances (pending -> running -> done/failed). A test, or the /stats surface, can observe
       completion without ears.

The clock is injectable (monotonic nanoseconds) so tests are deterministic. The store is guarded by
an RLock, because the request thread writes an entry that a background resume thread later mutates.
"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass
class PendingEntry:
    """One parked request. `extraction` is the opaque payload the resume needs.

    status advances pending -> running -> done | failed, or -> expired when the
    TTL elapses before a human answers.
    """

    pending_id : str
    extraction : Any
    user_email : str
    session_id : str
    user_id    : str
    created_ns : int
    command    : str                 = ""      # routing command — needed to rebuild the agent on resume
    question   : str                 = ""      # original question — folded with the resumed args (R-B4)
    status     : str                 = "pending"
    answer     : Optional[ str ]     = None
    error      : Optional[ str ]     = None


class PendingRequests:
    """A TTL-bounded, thread-safe store of parked flows keyed by pending_id.

    Requires:
        - ttl_seconds is a positive number of seconds.
        - clock is a zero-arg callable returning monotonically increasing
          nanoseconds (defaults to time.perf_counter_ns).

    Ensures:
        - put() stores an entry and returns its pending_id.
        - get() returns a live entry or None, evicting it first if expired.
        - set_status() advances a live entry's status/answer/error.
        - claim() atomically takes a live, still-pending entry and marks it
          running, so only one caller can own a resume.
        - sweep() evicts every expired entry and returns the count evicted.
        - the store never retains a dict/list handed in by reference.
    """

    def __init__(
        self,
        ttl_seconds : float                 = 3600.0,
        clock       : Callable[ [], int ]   = time.perf_counter_ns,
    ) -> None:
        self.ttl_ns   = int( ttl_seconds * 1_000_000_000 )
        self._clock   = clock
        self._lock    = threading.RLock()
        self._entries : Dict[ str, PendingEntry ] = {}

    def put(
        self,
        extraction  : Any,
        user_email  : str,
        session_id  : str,
        user_id     : str,
        command     : str             = "",
        question    : str             = "",
        pending_id  : Optional[ str ] = None,
    ) -> str:
        """
        Park a request and return its pending_id.

        Requires:
            - user_email, session_id, user_id are non-empty strings.

        Ensures:
            - a PendingEntry is stored under a fresh (or supplied) pending_id.
            - a dict/list/set extraction is copied so no shared reference is held.
            - command + question are persisted so resume can rebuild the agent —
              without them the parked entry is a receipt, not a continuation.
            - returns the pending_id.
        """
        pid     = pending_id if pending_id is not None else uuid.uuid4().hex
        payload = copy.copy( extraction ) if isinstance( extraction, ( dict, list, set ) ) else extraction
        entry   = PendingEntry(
            pending_id = pid,
            extraction = payload,
            user_email = user_email,
            session_id = session_id,
            user_id    = user_id,
            created_ns = self._clock(),
            command    = command,
            question   = question,
        )
        with self._lock:
            self._entries[ pid ] = entry
        return pid

    def _expired( self, entry: PendingEntry ) -> bool:
        """Return True iff `entry` is older than the TTL by the current clock."""
        return ( self._clock() - entry.created_ns ) > self.ttl_ns

    def get( self, pending_id: str ) -> Optional[ PendingEntry ]:
        """
        Return the live entry for `pending_id`, or None.

        Ensures:
            - an expired entry is evicted and None is returned.
            - a missing pending_id returns None.
        """
        with self._lock:
            entry = self._entries.get( pending_id )
            if entry is None:
                return None
            if self._expired( entry ):
                del self._entries[ pending_id ]
                return None
            return entry

    def release_turn( self, pending_id: str ) -> bool:
        """
        Hand a claimed conversation back to "pending" for its next turn.

        The interview-continue path calls this: it asked the next question and is
        done for now, so the entry must be answerable again. Without it, a
        multi-turn interview would claim on turn one and refuse every turn after.

        Ensures:
            - returns True and restores "pending" iff the entry is live and
              currently "answering"; returns False otherwise, so a terminal entry
              is never dragged back into an answerable state.
        """
        with self._lock:
            entry = self.get( pending_id )
            if entry is None or entry.status != "answering":
                return False
            entry.status = "pending"
            return True

    def claim( self, pending_id: str ) -> Optional[ PendingEntry ]:
        """
        Atomically take ownership of a parked entry for one resume turn.

        Requires:
            - pending_id is the id returned by a prior put().

        Ensures:
            - returns the entry with status "answering" iff it was live and
              still had status "pending"; the whole check-and-set happens under
              one lock acquisition. The caller owns the turn until it either
              release_turn()s (interview continues) or advances the status
              (the agent runs).
            - returns None if the entry is missing, expired, or already claimed.
              The caller cannot distinguish those, and must not: all three mean
              "this resume does not own the conversation".

        A resume turn is a read-modify-write spread over several calls. It reads the entry, folds the answer
        into its extraction, then either re-asks or runs the agent. The RLock keeps the dictionary
        structurally sound but does not make that sequence atomic.

        Two concurrent resumes on one pending_id could both pass the liveness check. Both would fold an
        answer into the same extraction object. On a two-argument interview that puts the answers in the
        wrong slots, because each caller takes `missing[ 0 ]` at a different moment. Racing two resumes of a
        location and date interview produced {"location": "Tuesday", "date": "Boston"} in four runs out of
        six.

        The race cannot happen while the resume handler runs on the event loop, because one loop cannot
        interleave two handlers. It becomes possible once the handler runs on a worker thread. This guard
        exists for that case.
        """
        with self._lock:
            entry = self.get( pending_id )
            if entry is None:
                return None
            if entry.status != "pending":
                return None
            entry.status = "answering"
            return entry

    def set_status(
        self,
        pending_id : str,
        status     : str,
        answer     : Optional[ str ] = None,
        error      : Optional[ str ] = None,
    ) -> bool:
        """
        Advance a live entry's status; the resume thread's completion seam.

        Requires:
            - status is a short lifecycle label ("running", "done", "failed", …).

        Ensures:
            - returns False if the entry is absent or already expired-evicted.
            - otherwise updates status (and answer/error when given) and returns
              True.
        """
        with self._lock:
            entry = self.get( pending_id )
            if entry is None:
                return False
            entry.status = status
            if answer is not None:
                entry.answer = answer
            if error is not None:
                entry.error = error
            return True

    def sweep( self ) -> int:
        """
        Evict every expired entry.

        Ensures:
            - returns the number of entries removed; the store keeps only live
              ones.
        """
        with self._lock:
            expired_ids : List[ str ] = [ pid for pid, entry in self._entries.items() if self._expired( entry ) ]
            for pid in expired_ids:
                del self._entries[ pid ]
            return len( expired_ids )

    def __len__( self ) -> int:
        with self._lock:
            return len( self._entries )

    def __contains__( self, pending_id: str ) -> bool:
        return self.get( pending_id ) is not None
