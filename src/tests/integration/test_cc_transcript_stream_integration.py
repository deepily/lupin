#!/usr/bin/env python3
"""
Integration tests for the console-tee transcript stream (phase 1).

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`, sha256 2603385fd183.
Names per ruling OSQ-6: `cc_transcript_watch` · `cc_transcript_unwatch` ·
`cc_transcript_append` · `cc_transcript_state`; REST `/api/cc-transcript/{cc_session_id}`.

What this file is, and how it differs from the plan's own tables
---------------------------------------------------------------
§2 and §3 tag nearly every acceptance criterion "unit tier, in-process TestClient,
tmp_path only". That is the right default and this file does not duplicate it. This is
the INTEGRATION complement: a real `/ws/queue` socket over the network, a real
`auth_request` handshake against the live auth stack, a real REST backlog call, and a
real server process that resolves the seat's transcript off disk. The unit tier proves
the handlers; this tier proves they are WIRED — mounted on the real socket, behind the
real gates, reading a real file.

CLAUDE.md § Tests: "Drive the assembled app, not only the class. A component can be
complete, correct, fully covered and never mounted, and every test that builds the
component stays green."

Venue: :8000, scheduled, submitted ONLY via `POST /api/test-suite/submit`
-----------------------------------------------------------------------
Forced by the rubric, on two counts: the tier registers users into `lupin_db_test`
(persistent state outliving the test) and it needs a real server. Never run it by
hand against :7999 and never inject it through a side door — a side door collides with
in-flight scheduled runs and poisons both.

The fixture, and why no live seat is involved
--------------------------------------------
Every scenario reads `src/tests/fixtures/cc_transcript/primary.jsonl` — a VERBATIM
contiguous window of a real completed Claude Code transcript, redacted, captured by
`capture_transcript_fixture.py` with provenance in `manifest.json`. A2.8/P2 require a
captured fixture rather than a hand-written one: a transcript is mostly not messages,
and a hand-written file is better-formed than reality exactly where the mapper depends
on the mess.

No live seat is used, which is A3.6/A8's requirement and also what makes these tests
deterministic. The seat is FIXTURED: the test writes a session-bridge file with a known
`stable_session_id` and a `transcript_path` pointing at its own copy of the fixture, and
the server resolves the seat through that bridge exactly as it would a real one.

🔴 THE PATH IN THAT BRIDGE MUST RESOLVE IDENTICALLY ON THE HOST AND INSIDE THE
CONTAINER, which is why these tests do NOT use `tmp_path`. `/tmp` is not mounted into
`lupin-rest-test`, so a bridge naming a `tmp_path` file points the server at nothing and
the tailer reports an empty transcript — a green-looking "no blocks" that is really a
mount problem. `docker-compose.yml:552-553` bind-mounts the host's sessions directory to
the SAME absolute path in the container, so a working directory underneath it is the one
place a path means the same thing to both sides. `seat_fixture` writes there and cleans
up after itself.

⚠️ Implementer, this is a contract on your side too: the tailer must open the
`transcript_path` the bridge gives it, verbatim, with no rewriting relative to a root.

Red until phase 1 lands — deliberately, and not with a skip
-----------------------------------------------------------
These tests are written before the server code exists, so they FAIL until the
Implementer's phase 1 is merged. That is the intended state and they carry no `skip` or
`xfail`: CLAUDE.md § Tests — "Unguarded is a third state", and a skipped test is an
unwatched one that reports green. ⇒ THEY MUST BE MERGED IN THE SAME COMMIT AS THE SERVER,
never ahead of it, or the integration gate reddens for a reason that is not a defect.
That sequencing is the Manager's to hold.
"""

import json
import os
import shutil
import sys
import time
import urllib.parse
import uuid

import pytest
import requests

from websockets.sync.client import connect as ws_connect

# The credential and admin fixtures come from src/tests/integration/conftest.py; its
# helper is imported by package path, matching test_job_history_api.py:18 — a bare
# `from conftest import ...` resolves to src/conftest.py, which is a different module.
from tests.integration.conftest import get_auth_header

# Defaults to the dedicated test container. Declared here rather than imported for the
# same reason its peers declare it (test_job_history_api.py:22, test_admin_users.py:91).
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )


# ── constants drawn from the plan, not invented here ──────────────────────────

WATCH_EVENT   = "cc_transcript_watch"
UNWATCH_EVENT = "cc_transcript_unwatch"
APPEND_EVENT  = "cc_transcript_append"
STATE_EVENT   = "cc_transcript_state"

CC_TRANSCRIPT_EVENTS = [ WATCH_EVENT, UNWATCH_EVENT, APPEND_EVENT, STATE_EVENT ]

# Ruling Q7 batches pushes about every 300 ms. Waits below are expressed as a multiple of
# that rather than as a number, so a change to the dial moves one constant.
COALESCE_MS       = 300
FRAME_TIMEOUT_S   = ( COALESCE_MS / 1000.0 ) * 20     # 6s — generous; a slow box is not a defect
HANDSHAKE_TIMEOUT = 10.0

FIXTURE_DIR  = os.path.join(
    os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "tests", "fixtures", "cc_transcript"
)
PRIMARY_FIXTURE = os.path.join( FIXTURE_DIR, "primary.jsonl" )

# The one rw path that means the same thing to the host and to the container — see the
# module docstring. Overridable for a non-default compose setup.
HOST_SESSIONS_DIR = os.environ.get( "LUPIN_HOST_SESSIONS_DIR", os.path.expanduser( "~/.claude/sessions" ) )
SEAT_WORK_DIR     = os.path.join( HOST_SESSIONS_DIR, "cc-transcript-itest" )


# ── a synchronous /ws/queue client ────────────────────────────────────────────

class QueueSocket:
    """
    A real authenticated `/ws/queue/{session_id}` connection with send and recv.

    The `ws_connection` fixture in conftest.py opens a socket and HOLDS it open in a
    background thread — it exists so `is_user_connected()` reports True, and it never
    reads a frame the test chooses. These scenarios need the opposite: send a verb, then
    read the frames that come back, in order. `websockets.sync.client` gives that without
    an event loop, so the assertions read top to bottom.

    Requires:
        - a live server at BASE_URL with /ws/queue mounted
        - access_token is a JWT the server will accept

    Ensures:
        - the context manager yields only after `auth_success` has been received
        - recv_frame returns decoded dicts and raises on timeout rather than hanging
    """

    def __init__( self, access_token, subscribed_events, session_id=None ):
        self.access_token      = access_token
        self.subscribed_events = subscribed_events
        self.session_id        = session_id or f"itest {uuid.uuid4().hex[ :8 ]}"
        self._socket           = None
        self.auth_frame        = None

    def __enter__( self ):
        host    = BASE_URL.replace( "http://", "" ).replace( "https://", "" )
        encoded = urllib.parse.quote( self.session_id )
        self._socket = ws_connect( f"ws://{host}/ws/queue/{encoded}", open_timeout=HANDSHAKE_TIMEOUT )
        self.send( {
            "type"              : "auth_request",
            "token"             : f"Bearer {self.access_token}",
            "subscribed_events" : self.subscribed_events,
        } )
        self.auth_frame = self.recv_frame( expect=None, timeout=HANDSHAKE_TIMEOUT )
        return self

    def __exit__( self, *_exc ):
        if self._socket is not None: self._socket.close()

    def send( self, payload ):
        self._socket.send( json.dumps( payload ) )

    def recv_frame( self, expect=None, timeout=FRAME_TIMEOUT_S ):
        """
        Read the next frame, optionally skipping past frames of other types.

        `expect=None` returns the very next frame whatever it is — used for the
        handshake, where reading past an `auth_error` would turn a refusal into a
        timeout and hide which one happened.

        Requires:
            - the socket is open

        Ensures:
            - returns the first decoded frame whose `type` is in `expect`, or the next
              frame at all when expect is None

        Raises:
            - AssertionError, naming the frames it did see, if the deadline passes
        """
        wanted   = None if expect is None else ( { expect } if isinstance( expect, str ) else set( expect ) )
        deadline = time.monotonic() + timeout
        seen     = []
        while time.monotonic() < deadline:
            remaining = max( 0.05, deadline - time.monotonic() )
            try:
                raw = self._socket.recv( timeout=remaining )
            except TimeoutError:
                break
            frame = json.loads( raw )
            if wanted is None or frame.get( "type" ) in wanted: return frame
            seen.append( frame.get( "type" ) )
        raise AssertionError(
            f"no frame of type {sorted( wanted ) if wanted else '<any>'} within {timeout}s; "
            f"saw {seen or 'nothing'}"
        )

    def drain( self, seconds=None ):
        """Collect every frame that arrives inside a window. Used to prove ABSENCE."""
        window   = ( COALESCE_MS / 1000.0 ) * 6 if seconds is None else seconds
        deadline = time.monotonic() + window
        frames   = []
        while time.monotonic() < deadline:
            remaining = max( 0.05, deadline - time.monotonic() )
            try:
                frames.append( json.loads( self._socket.recv( timeout=remaining ) ) )
            except TimeoutError:
                break
        return frames


# ── the fixtured seat ─────────────────────────────────────────────────────────

class SeatFixture:
    """
    A fixtured Claude Code seat: a bridge file plus a transcript file on disk.

    Attributes:
        cc_session_id   the seat's `stable_session_id` — the FULL id, per the §3 rule
                        that `cc_session_id` is never the 8-hex form the fleet uses
                        elsewhere. A3.6 checks that width across surfaces.
        transcript_path the path the bridge names, identical on host and in container
        bridge_path     the session-bridge file the server resolves the seat through
    """

    def __init__( self, root ):
        self.cc_session_id   = str( uuid.uuid4() )
        self.root            = root
        self.transcript_path = os.path.join( root, f"{self.cc_session_id}.jsonl" )
        self.bridge_path     = os.path.join( root, f"cc-itest-{self.cc_session_id[ :8 ]}.json" )

    # ── transcript ────────────────────────────────────────────────────────────

    def seed_bytes( self, byte_count ):
        """
        Write the first whole lines of the captured fixture totalling <= byte_count.

        Whole lines, because §3 says `next_offset` always lands at the end of a complete
        line. Seeding a partial line would make the server's first offset a property of
        this helper rather than of the file.

        Requires:
            - byte_count is a positive int

        Ensures:
            - the transcript exists and its size is <= byte_count
            - it ends on a newline
            - returns the size actually written
        """
        written = bytearray()
        with open( PRIMARY_FIXTURE, "rb" ) as source:
            for line in source:
                if len( written ) + len( line ) > byte_count: break
                written += line
        assert written, f"byte_count={byte_count} is smaller than the fixture's first line"
        with open( self.transcript_path, "wb" ) as handle: handle.write( bytes( written ) )
        return len( written )

    def append_next_lines( self, count ):
        """
        Append the next `count` whole fixture lines, simulating the seat writing more.

        Ensures:
            - returns ( bytes_appended, new_size )
        """
        current = os.path.getsize( self.transcript_path )
        added   = bytearray()
        with open( PRIMARY_FIXTURE, "rb" ) as source:
            source.seek( current )
            for _ in range( count ):
                line = source.readline()
                if not line or not line.endswith( b"\n" ): break
                added += line
        assert added, "the fixture has no further whole lines — seed a smaller prefix"
        with open( self.transcript_path, "ab" ) as handle: handle.write( bytes( added ) )
        return len( added ), current + len( added )

    def swap_transcript_path( self ):
        """
        Simulate a `/clear`: a NEW transcript path, the SAME stable_session_id.

        P1 measured this as the real mechanism — `register_session.py` runs on every
        SessionStart, `/clear` fires SessionStart, and the hook rewrites the bridge with
        the new `transcript_path` while PRESERVING `stable_session_id`. The old file does
        not shrink; it simply stops growing. A tailer watching only for a shrink freezes
        forever on the dead file.

        Ensures:
            - the bridge names a different, existing transcript file
            - cc_session_id is unchanged
            - returns the new path
        """
        new_path = os.path.join( self.root, f"{uuid.uuid4()}.jsonl" )
        shutil.copyfile( PRIMARY_FIXTURE, new_path )
        self.transcript_path = new_path
        self.write_bridge()
        return new_path

    # ── bridge ────────────────────────────────────────────────────────────────

    def write_bridge( self ):
        """
        Write the session-bridge file the server resolves `transcript_path` from.

        The shape mirrors a real bridge: `stable_session_id` and `transcript_path` side by
        side, the path carrying the per-session uuid, exactly as P1 verified on a live
        file.
        """
        payload = {
            "session_id"        : self.cc_session_id,
            "stable_session_id" : self.cc_session_id,
            "transcript_path"   : self.transcript_path,
            "project"           : "lupin",
            "persona_name"      : "Fixtured Seat",
            "cwd"               : self.root,
        }
        with open( self.bridge_path, "w", encoding="utf-8" ) as handle:
            json.dump( payload, handle, indent=2 )

    def cleanup( self ):
        for path in ( self.bridge_path, self.transcript_path ):
            if os.path.exists( path ): os.remove( path )


@pytest.fixture( scope="function" )
def seat_fixture():
    """
    A fixtured seat under the bind-mounted sessions directory, cleaned up afterwards.

    Requires:
        - HOST_SESSIONS_DIR exists and is writable (it is the compose bind-mount source)
        - the captured fixture is present

    Ensures:
        - yields a SeatFixture whose transcript is seeded with the fixture's first 48 KB
          and whose bridge has been written
        - every file it created is removed on teardown, whatever the test did
    """
    assert os.path.isfile( PRIMARY_FIXTURE ), (
        f"{PRIMARY_FIXTURE} is missing — run "
        f"src/tests/fixtures/cc_transcript/capture_transcript_fixture.py on a host with "
        f"real Claude Code transcripts"
    )
    assert os.path.isdir( HOST_SESSIONS_DIR ), (
        f"{HOST_SESSIONS_DIR} does not exist. The bridge file has to live on a path the "
        f"container sees at the same absolute location (docker-compose.yml:552-553); "
        f"tmp_path will not do. Set LUPIN_HOST_SESSIONS_DIR if your compose differs."
    )
    os.makedirs( SEAT_WORK_DIR, exist_ok=True )

    seat = SeatFixture( SEAT_WORK_DIR )
    # 48 KB is under ruling Q6's 64 KB cap on purpose: it leaves the whole seeded
    # transcript inside one backlog page, so a backlog assertion is about the server's
    # offsets and not about where the cap happened to fall.
    seat.seed_bytes( 48 * 1024 )
    seat.write_bridge()
    yield seat
    seat.cleanup()


# ── helpers ───────────────────────────────────────────────────────────────────

def line_boundary_at_or_before( path, target ):
    """
    Return the largest complete-line boundary <= target.

    §3 promises every offset lands at the end of a complete line, so a test that asked to
    resume from an arbitrary byte would be asking for something the contract does not
    define — and the server's answer would be a judgement call rather than a pass or a
    fail.

    Requires:
        - path names a newline-terminated file
        - 0 <= target <= the file's size

    Ensures:
        - returns 0, or an offset whose preceding byte is a newline
        - the result is <= target
    """
    with open( path, "rb" ) as handle: raw = handle.read( target )
    return raw.rfind( b"\n" ) + 1


def backlog_url( cc_session_id, **params ):
    query = urllib.parse.urlencode( params )
    return f"{BASE_URL}/api/cc-transcript/{cc_session_id}" + ( f"?{query}" if query else "" )


def watch( socket, seat, from_offset, file_epoch=None ):
    socket.send( {
        "type"          : WATCH_EVENT,
        "cc_session_id" : seat.cc_session_id,
        "from_offset"   : from_offset,
        "file_epoch"    : file_epoch,
    } )


def blocks_of( frames ):
    out = []
    for frame in frames:
        if frame.get( "type" ) == APPEND_EVENT: out.extend( frame.get( "blocks", [] ) )
    return out


@pytest.fixture( scope="function" )
def admin_socket_events():
    """The subscription list a console pane would send — the four names plus the handshake."""
    return [ "auth_success", "auth_error" ] + CC_TRANSCRIPT_EVENTS


# ═══════════════════════════════════════════════════════════════════════════════
# 1 — the socket, the handshake, and the gate on it
# ═══════════════════════════════════════════════════════════════════════════════

def test_an_admin_authenticates_on_the_real_socket_and_its_subscription_survives(
    create_test_admin, admin_socket_events
):
    """
    The real handshake, and the T3 failure mode asserted rather than assumed.

    T3: a name absent from `websocket available events` is dropped at subscribe time,
    SILENTLY — a client whose whole list validates to `[]` has every frame dropped while
    auth reports success. So `auth_success` alone does not establish that the four
    cc_transcript names were accepted. This asserts the server echoes them back as
    subscribed; the INI-side half is the unit tier's A2.6.
    """
    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        assert socket.auth_frame[ "type" ] == "auth_success", socket.auth_frame

        echoed = socket.auth_frame.get( "subscribed_events" )
        assert echoed is not None, (
            "auth_success did not report the accepted subscription list, so a client "
            "cannot tell an accepted name from a silently dropped one — the exact "
            "condition the in-place comment at websocket_manager.py:207-219 describes"
        )
        missing = [ name for name in CC_TRANSCRIPT_EVENTS if name not in echoed ]
        assert not missing, f"these names validated away silently: {missing}"


def test_a_non_admin_watch_is_refused_and_no_blocks_follow( create_test_user, seat_fixture, admin_socket_events ):
    """
    A2.2's NEGATIVE arm on the WS surface, over the real gate (`session_is_admin`).

    Ruling Q5 is admin-only, and the console carries everything the seat read. The
    refusal is asserted together with the ABSENCE of any append frame: a server that
    answered a refusal and streamed anyway would pass a refusal-only assertion.
    """
    with QueueSocket( create_test_user[ "access_token" ], admin_socket_events ) as socket:
        assert socket.auth_frame[ "type" ] == "auth_success", "the socket itself is not admin-gated"
        watch( socket, seat_fixture, from_offset=0 )

        frames  = socket.drain()
        appends = [ f for f in frames if f.get( "type" ) == APPEND_EVENT ]
        assert not appends, f"a non-admin received {len( appends )} append frame(s)"

        states = [ f for f in frames if f.get( "type" ) == STATE_EVENT ]
        assert states, "the watch was neither honoured nor refused — a silent drop"
        assert any( "denied" in str( f.get( "state" ) ) or "forbidden" in str( f.get( "state" ) ) for f in states ), (
            f"the refusal does not name itself: {states}"
        )


def test_an_admin_watch_is_accepted_over_the_real_auth_stack( create_test_admin, seat_fixture, admin_socket_events ):
    """
    A2.2's POSITIVE arm, and the one the plan says nobody can execute.

    A2.2b records the positive arm as blocked and Rick ruled v1 ships on the
    override-tier arm, on the stated grounds that "the only admin accounts are
    admin@lupin.deepily.ai and Rick's own and neither password is held by the fleet".
    That reason is true of the PRODUCTION database and does not travel to this tier:
    `create_test_admin` (conftest.py:323) registers an admin into `lupin_db_test`,
    promotes it through UserRepository, then logs in for a real token — and
    `test_admin_users.py:307` already watches a `require_admin`-gated PUT answer 200 on
    it. So the positive arm runs here over the real stack, not an override.

    This does NOT retire A2.2's override-tier arm; both are wanted, and the unit tier's
    is faster. It retires the claim that the seam cannot be driven.
    """
    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        watch( socket, seat_fixture, from_offset=0 )
        frame = socket.recv_frame( expect=[ APPEND_EVENT, STATE_EVENT ] )

        assert frame[ "cc_session_id" ] == seat_fixture.cc_session_id
        if frame[ "type" ] == STATE_EVENT:
            assert frame[ "state" ] == "live", f"admin watch was not accepted: {frame}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2 — watch from an offset, and the offsets chain
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_watch_starts_where_the_client_asked_not_at_the_end_of_the_file(
    create_test_admin, seat_fixture, admin_socket_events
):
    """
    §3: "The server starts where the client asked. A watch honours `from_offset` and
    never silently starts at the current end of the file."

    Tiffany F3 names the consequence: the window between a REST backlog fetch and the
    live watch becomes a silent gap. Prove it discriminates — a server that ignored
    `from_offset` and tailed from the end would deliver nothing here, because the seeded
    transcript stops growing during this test.
    """
    size        = os.path.getsize( seat_fixture.transcript_path )
    from_offset = line_boundary_at_or_before( seat_fixture.transcript_path, size // 2 )

    assert 0 < from_offset < size, (
        "the requested offset has to be strictly inside the file, or 'started where asked' "
        "and 'started at the beginning' are the same answer"
    )

    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        watch( socket, seat_fixture, from_offset=from_offset )
        frame = socket.recv_frame( expect=APPEND_EVENT )

        assert frame[ "offset" ] == from_offset, (
            f"the server started at {frame[ 'offset' ]}, not the requested {from_offset}. "
            f"0 would mean it ignored the offset; {size} would mean it tailed from the end "
            f"— the silent-gap defect Tiffany F3 names"
        )
        assert frame[ "next_offset" ] == size, "the server did not read through to the end of the file"
        assert frame[ "blocks" ], "an append frame carried no blocks"


def test_append_frames_arrive_in_order_with_offsets_that_chain(
    create_test_admin, seat_fixture, admin_socket_events
):
    """
    A2.1: every byte from N onward, in order, with no gap and no repeat.

    `offset` IS the sequence number — there is no separate `seq` (§3) — so "in order"
    and "chaining" are one assertion: each frame's `offset` equals the previous frame's
    `next_offset`, and `next_offset` lands at the end of a complete line.

    The seat is made to write in several bursts rather than one, because a single burst
    coalesces into a single frame (ruling Q7's ~300 ms batch) and a one-frame stream
    cannot show a chain.
    """
    seeded = seat_fixture.seed_bytes( 8 * 1024 )

    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        watch( socket, seat_fixture, from_offset=0 )
        first = socket.recv_frame( expect=APPEND_EVENT )
        assert first[ "offset" ] == 0

        chain = [ first ]
        for _ in range( 3 ):
            time.sleep( ( COALESCE_MS * 2 ) / 1000.0 )   # let the previous batch close
            seat_fixture.append_next_lines( 2 )
            chain.append( socket.recv_frame( expect=APPEND_EVENT ) )

        assert len( chain ) >= 4, "the bursts did not produce separate frames"

        for previous, current in zip( chain, chain[ 1: ] ):
            assert current[ "offset" ] == previous[ "next_offset" ], (
                f"offsets do not chain: frame at {current[ 'offset' ]} followed "
                f"next_offset {previous[ 'next_offset' ]} — a gap or a repeat"
            )
            assert current[ "next_offset" ] > current[ "offset" ]
            assert current[ "file_epoch" ] == first[ "file_epoch" ], "the epoch moved mid-stream"

        # next_offset lands on a complete line — read the file at that offset and the
        # byte before it must be a newline. This is the property `tail_session_file`
        # provides and the contract promises; asserting it here is what makes a
        # mid-line offset a failure rather than a later parse error.
        final = chain[ -1 ][ "next_offset" ]
        with open( seat_fixture.transcript_path, "rb" ) as handle:
            handle.seek( final - 1 )
            assert handle.read( 1 ) == b"\n", f"next_offset {final} is mid-line"

        assert final > seeded, "nothing was appended beyond the seed"


# ═══════════════════════════════════════════════════════════════════════════════
# 3 — the gap rule and its ONE REST repair
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_gap_is_repaired_by_exactly_one_rest_fetch_that_closes_it(
    create_test_admin, seat_fixture, admin_socket_events
):
    """
    §3 gap rule: "if `chunk.offset != last_next_offset`, drop the chunk and fetch over
    REST from `last_next_offset`."

    The rule is the CLIENT's, and phase 1 ships no client — so what this tier can verify
    is the half the rule depends on: that the REST repair fetch a client would issue
    actually closes the gap it was handed. The client-side drop-and-refetch is A3.2,
    executed by B4.1 and C5.1.

    "Exactly one" is asserted as a property of the ANSWER, not by counting calls: the
    single fetch from `last_next_offset` must return bytes that reach the live frame's
    offset, leaving nothing for a second round trip. A repair that needed two fetches
    would leave a residue here.
    """
    seat_fixture.seed_bytes( 4 * 1024 )
    headers = get_auth_header( create_test_admin[ "access_token" ] )

    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        watch( socket, seat_fixture, from_offset=0 )
        first            = socket.recv_frame( expect=APPEND_EVENT )
        last_next_offset = first[ "next_offset" ]

        # Grow the file well past one batch so the next live frame is demonstrably ahead
        # of last_next_offset — the gap a client would observe after missing a chunk.
        for _ in range( 4 ): seat_fixture.append_next_lines( 3 )
        time.sleep( ( COALESCE_MS * 3 ) / 1000.0 )
        live = socket.recv_frame( expect=APPEND_EVENT )

        response = requests.get(
            backlog_url( seat_fixture.cc_session_id, since_offset=last_next_offset ),
            headers=headers, timeout=30,
        )
        assert response.status_code == 200, response.text
        repair = response.json()

        assert repair[ "offset" ] == last_next_offset, (
            f"the repair started at {repair[ 'offset' ]}, not the requested "
            f"{last_next_offset} — the gap is not closed, it is moved"
        )
        assert repair[ "file_epoch" ] == first[ "file_epoch" ], "the repair is from a different file"
        assert repair[ "blocks" ], "the repair returned no blocks for a gap that had bytes in it"
        assert repair[ "next_offset" ] >= live[ "offset" ], (
            f"one fetch reached {repair[ 'next_offset' ]} but the live stream is already at "
            f"{live[ 'offset' ]} — the client would need a second round trip, so the gap "
            f"rule as written does not converge"
        )


def test_the_backlog_pages_backwards_as_ruling_q6_requires( create_test_admin, seat_fixture ):
    """
    A2.9 / P4: a forward-only contract cannot express ruling Q6.

    Q6 ruled "since last `/clear`, capped ~64 KB, load earlier". `?since_offset=0&
    max_bytes=65536` returns the FIRST 64 KB; Q6 wants the LAST 64 KB and a page going
    backwards from a known offset. Prove it discriminates: the fixture is sized past the
    cap on purpose (197 KB, three times 64 KB), so `tail_bytes` and `since_offset=0`
    MUST return different bytes — at or under the cap they would agree and a forward-only
    server would pass.
    """
    shutil.copyfile( PRIMARY_FIXTURE, seat_fixture.transcript_path )
    total   = os.path.getsize( seat_fixture.transcript_path )
    headers = get_auth_header( create_test_admin[ "access_token" ] )
    cap     = 65536
    assert total > 2 * cap, f"fixture is {total} bytes; the discrimination below needs > {2 * cap}"

    tail = requests.get( backlog_url( seat_fixture.cc_session_id, tail_bytes=cap ), headers=headers, timeout=30 )
    assert tail.status_code == 200, tail.text
    tail_body = tail.json()

    head = requests.get( backlog_url( seat_fixture.cc_session_id, since_offset=0, max_bytes=cap ), headers=headers, timeout=30 )
    assert head.status_code == 200, head.text
    head_body = head.json()

    assert tail_body[ "offset" ] > head_body[ "offset" ], (
        f"tail_bytes returned offset {tail_body[ 'offset' ]} and since_offset=0 returned "
        f"{head_body[ 'offset' ]} — tail_bytes is reading FORWARD from the start"
    )
    assert tail_body[ "next_offset" ] == total, (
        f"tail_bytes ended at {tail_body[ 'next_offset' ]}, not the file's end {total}"
    )

    # ── "load earlier": a backward page from the tail's own start ─────────────
    earlier = requests.get(
        backlog_url( seat_fixture.cc_session_id, before_offset=tail_body[ "offset" ], max_bytes=cap ),
        headers=headers, timeout=30,
    )
    assert earlier.status_code == 200, earlier.text
    earlier_body = earlier.json()

    assert earlier_body[ "next_offset" ] == tail_body[ "offset" ], (
        "the backward page does not abut the page it was asked to precede, so paging "
        "backwards would skip or repeat bytes"
    )
    assert earlier_body[ "offset" ] < tail_body[ "offset" ]

    # Both boundaries land on complete lines — the contract's rule, at the one place a
    # backward read is most likely to break it.
    with open( seat_fixture.transcript_path, "rb" ) as handle:
        for boundary in ( tail_body[ "offset" ], earlier_body[ "offset" ] ):
            if boundary == 0: continue
            handle.seek( boundary - 1 )
            assert handle.read( 1 ) == b"\n", f"boundary {boundary} is mid-line"


# ═══════════════════════════════════════════════════════════════════════════════
# 4 — epoch: a stale watch is refused, never rebased
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_watch_naming_a_stale_epoch_is_refused_and_not_rebased(
    create_test_admin, seat_fixture, admin_socket_events
):
    """
    A3.5 / T15: "A stale non-null epoch is refused, never silently rebased."

    This is the first message every reconnecting client sends after a `/clear` it did not
    see. A silent rebase would hand the client the whole NEW file labelled as its own
    continuation — which is why the absence of blocks is asserted as hard as the state
    frame's presence.
    """
    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        watch( socket, seat_fixture, from_offset=0, file_epoch=None )
        first     = socket.recv_frame( expect=[ APPEND_EVENT, STATE_EVENT ] )
        old_epoch = first[ "file_epoch" ]
        assert old_epoch, "the server did not answer with the epoch it chose, so a client sending null cannot learn one"
        socket.send( { "type": UNWATCH_EVENT, "cc_session_id": seat_fixture.cc_session_id } )

    new_path  = seat_fixture.swap_transcript_path()
    new_size  = os.path.getsize( new_path )

    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        watch( socket, seat_fixture, from_offset=new_size // 2, file_epoch=old_epoch )
        frames = socket.drain()

        states = [ f for f in frames if f.get( "type" ) == STATE_EVENT ]
        assert states, f"a stale epoch produced no state frame; saw {[ f.get( 'type' ) for f in frames ]}"
        mismatch = [ f for f in states if f.get( "state" ) == "epoch_mismatch" ]
        assert mismatch, f"expected state 'epoch_mismatch', got {[ f.get( 'state' ) for f in states ]}"

        assert mismatch[ 0 ][ "file_epoch" ] != old_epoch, (
            "epoch_mismatch echoed the stale epoch back; the client cannot learn the "
            "current one and will re-send the same stale watch forever"
        )
        assert not blocks_of( frames ), (
            "blocks were delivered alongside epoch_mismatch — this is the silent rebase "
            "T15 forbids, and the client would render the new file as its own continuation"
        )


def test_a_clear_swaps_the_path_and_the_epoch_follows_it( create_test_admin, seat_fixture, admin_socket_events ):
    """
    A2.3 arm (a) — the PATH SWAP, which is the real `/clear` and the defect P1 found.

    A `/clear` never shrinks the file: the hook rewrites the bridge with a new
    `transcript_path` and preserves `stable_session_id`, so the old JSONL simply stops
    growing. Prove it watches: a tailer that only checks for a shrink CANNOT pass this —
    it sits on the dead file forever, with no epoch bump and no state frame, and the pane
    silently freezes at every clear.
    """
    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        watch( socket, seat_fixture, from_offset=0 )
        before = socket.recv_frame( expect=APPEND_EVENT )

        seat_fixture.swap_transcript_path()

        state = socket.recv_frame( expect=STATE_EVENT, timeout=FRAME_TIMEOUT_S * 2 )
        assert state[ "state" ] == "rotated", (
            f"a path swap produced state {state.get( 'state' )!r}; A2.10 requires the "
            f"epoch change to be SIGNALLED as a frame, not just applied"
        )
        assert state[ "file_epoch" ] != before[ "file_epoch" ], "the epoch did not move with the path"
        assert state[ "cc_session_id" ] == seat_fixture.cc_session_id, (
            "the seat identity changed across a /clear; stable_session_id must survive it"
        )

        after = socket.recv_frame( expect=APPEND_EVENT, timeout=FRAME_TIMEOUT_S * 2 )
        assert after[ "file_epoch" ] == state[ "file_epoch" ]
        assert after[ "offset" ] == 0, f"the new file was not read from 0, but from {after[ 'offset' ]}"


# ═══════════════════════════════════════════════════════════════════════════════
# 5 — the REST backlog's own gate, both arms
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_rest_backlog_refuses_a_non_admin_and_serves_an_admin( create_test_user, create_test_admin, seat_fixture ):
    """
    A2.2 on the REST surface, both arms in one test.

    The two surfaces use DIFFERENT gates — `session_is_admin` on the socket,
    `require_admin` on the route (T9) — so a WS-only refusal test leaves the REST gate
    unwatched, and a criterion satisfiable by a gate that refuses everyone is no
    criterion at all (A3). Both arms, over the real stack, on the same route.
    """
    url = backlog_url( seat_fixture.cc_session_id, since_offset=0 )

    refused = requests.get( url, headers=get_auth_header( create_test_user[ "access_token" ] ), timeout=30 )
    assert refused.status_code == 403, (
        f"a non-admin got {refused.status_code} from the backlog route; ruling Q5 is "
        f"admin-only and the console carries whatever the seat read"
    )

    served = requests.get( url, headers=get_auth_header( create_test_admin[ "access_token" ] ), timeout=30 )
    assert served.status_code == 200, (
        f"an admin got {served.status_code}: {served.text}. Without this arm the test "
        f"above would pass against a route that refuses everyone."
    )
    body = served.json()
    for field in ( "file_epoch", "offset", "next_offset", "blocks" ):
        assert field in body, f"the backlog response is missing {field!r}: {sorted( body )}"


def test_the_backlog_route_refuses_an_unauthenticated_caller( seat_fixture ):
    """
    401 and 403 are different answers and only one of them is about roles.

    Without this, a route that answered 403 to everyone — including anonymous callers —
    would satisfy the non-admin arm above while telling us nothing about the gate.
    """
    response = requests.get( backlog_url( seat_fixture.cc_session_id, since_offset=0 ), timeout=30 )
    assert response.status_code == 401, f"expected 401 unauthenticated, got {response.status_code}"


# ═══════════════════════════════════════════════════════════════════════════════
# 6 — the id width, across surfaces (A3.6)
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_seat_id_is_one_string_at_one_width_across_the_two_surfaces(
    create_test_admin, seat_fixture, admin_socket_events
):
    """
    A3.6, from the FIXTURED bridge — never a live seat.

    Three id widths circulate in this fleet: the full `stable_session_id`, the post-clear
    id, and the 8-hex form in `sender_id` and `recipient_session_hash8`. §3 rules that
    `cc_session_id` is the full `stable_session_id`, and a silent mismatch shows up as a
    roster row that cannot be watched. Asserted ACROSS the two surfaces, never within
    one: comparing the stream's id to itself is a tautology.
    """
    bridge_value = json.load( open( seat_fixture.bridge_path, encoding="utf-8" ) )[ "stable_session_id" ]

    backlog = requests.get(
        backlog_url( seat_fixture.cc_session_id, since_offset=0 ),
        headers=get_auth_header( create_test_admin[ "access_token" ] ), timeout=30,
    )
    assert backlog.status_code == 200, backlog.text

    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        watch( socket, seat_fixture, from_offset=0 )
        frame = socket.recv_frame( expect=[ APPEND_EVENT, STATE_EVENT ] )

    assert frame[ "cc_session_id" ] == bridge_value, (
        f"the stream calls the seat {frame[ 'cc_session_id' ]!r} and the bridge calls it "
        f"{bridge_value!r}"
    )
    assert len( bridge_value ) == 36, (
        f"the bridge's stable_session_id is {len( bridge_value )} characters, not a full "
        f"uuid — §3 forbids the 8-hex form here"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 7 — the watcher registry does not leak on a dropped socket (A2.5 arm b)
# ═══════════════════════════════════════════════════════════════════════════════

def test_a_dropped_socket_ends_the_watch_without_an_unwatch( create_test_admin, seat_fixture, admin_socket_events ):
    """
    A2.5 arm (b), the leak P3 names — and the arm that can only be driven from a real
    socket, which is why it sits in this tier rather than the unit one.

    A closed tab never sends `cc_transcript_unwatch`. If `disconnect()`'s hand-maintained
    sweep does not include the watcher map, the tailer polls forever and `emit_to_session`
    early-returns into a session already gone from `active_connections`: a silent burn
    with no error anywhere. The sweep is a SIXTH entry someone has to remember to add.

    Observed from the outside, without reaching into server state: a second socket
    watching the same seat after the first was dropped must still be served. A server
    that had leaked the dead watcher would either serve the dead session (unobservable
    here) or, more usefully, fail to re-register the live one.
    """
    socket = QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ).__enter__()
    watch( socket, seat_fixture, from_offset=0 )
    socket.recv_frame( expect=[ APPEND_EVENT, STATE_EVENT ] )

    socket._socket.close()                       # a closed tab: no unwatch verb is sent
    time.sleep( ( COALESCE_MS * 4 ) / 1000.0 )

    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as fresh:
        watch( fresh, seat_fixture, from_offset=0 )
        frame = fresh.recv_frame( expect=[ APPEND_EVENT, STATE_EVENT ] )
        assert frame[ "cc_session_id" ] == seat_fixture.cc_session_id, (
            "a new watcher on the same seat was not served after the previous socket "
            "dropped without unwatching — the registry is holding a dead entry"
        )


def test_the_channel_has_no_client_to_seat_verb( create_test_admin, seat_fixture, admin_socket_events ):
    """
    Ruling Q8: read-only by construction — the only client verbs are watch and unwatch.

    Enumerate the surface, not the traffic: this sends a plausible write verb and asserts
    the server does not act on it. It cannot prove no such verb exists anywhere; what it
    can do is fail loudly if one is added later, which is the guard worth having.
    """
    with QueueSocket( create_test_admin[ "access_token" ], admin_socket_events ) as socket:
        watch( socket, seat_fixture, from_offset=0 )
        socket.recv_frame( expect=[ APPEND_EVENT, STATE_EVENT ] )

        socket.send( {
            "type"          : "cc_transcript_send",
            "cc_session_id" : seat_fixture.cc_session_id,
            "text"          : "this must not reach the seat",
        } )
        time.sleep( ( COALESCE_MS * 3 ) / 1000.0 )

        body = open( seat_fixture.transcript_path, encoding="utf-8", errors="replace" ).read()
        assert "this must not reach the seat" not in body, (
            "a client→seat verb was honoured; ruling Q8 makes this channel read-only"
        )


if __name__ == "__main__":
    print( "This tier runs on :8000 only, via POST /api/test-suite/submit. See the module docstring." )
    sys.exit( 2 )
