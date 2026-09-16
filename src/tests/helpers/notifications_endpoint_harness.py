"""
Shared endpoint harness for `cosa.rest.routers.notifications`.

WHY THIS MODULE EXISTS. The router is ~3,300 lines holding 23 routed endpoints, and
essentially every one of them needs the SAME five things stood up before a single
assertion can run: a FastAPI app carrying the router, an auth override, a `get_db`
context-manager stub, a `NotificationRepository` spy, and — the one that is easy to
miss — stubs for `lupin_app.main.config_mgr` / `app_debug`. Standing those up per file
cost most of a batch the first time. Factoring them here makes the remaining endpoint
files cheap enough to be worth writing.

🔴 THE TRAP THIS MODULE EXISTS TO CLOSE. Nearly every success envelope in the router
calls `get_local_timestamp()`, which reads `lupin_app.main.config_mgr`. In a unit
context that attribute does not exist, the read raises, and the handler's blanket
`except Exception` converts it to a 500 — so EVERY endpoint returns 500 and the tests
measure the error path while reporting on the happy one. It is silent because a 500
is a perfectly ordinary thing for an error test to expect. The harness stubs it, and
`assert_no_accidental_500()` is provided so a file can refuse to be fooled.

🔴 THE DESIGN RULE EVERY DEFAULT HERE FOLLOWS: make the WRONG answer a DIFFERENT
answer. That is why —
  - the repo spy is STRICT: a method the test did not program RAISES, so a handler
    calling the wrong repo method surfaces as a failure instead of quietly receiving
    `None` and carrying on;
  - the frozen timestamp is a fixed, obviously-synthetic instant, so a handler that
    substituted `datetime.now()` produces a different string rather than a plausible
    one;
  - the session handed out by the `get_db` stub is a unique sentinel object, so
    "the repo was built on the session" is checkable rather than assumed;
  - every call is recorded with its args AND kwargs, so `limit=` arriving as a
    positional, or not arriving at all, is visible.

USAGE — one line per test file:

    from tests.helpers.notifications_endpoint_harness import make_harness_fixture
    harness = make_harness_fixture()

    def test_it_returns_what_the_repo_gave( harness ):
        harness.repo.returns( "get_by_id", _Row() )
        body = harness.client.get( "/api/notifications/response/<id>" ).json()
        assert body[ "state" ] == "STATE-VALUE"
        harness.repo.assert_only_called( "get_by_id" )
"""

import os
import sys
import uuid

import pytest

# Bootstrap: mirror the unit-tier import bootstrap so this module is importable
# whether or not the caller already inserted src/ on the path.
_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root:
    _src_path = os.path.join( _lupin_root, "src" )
    if _src_path not in sys.path:
        sys.path.insert( 0, _src_path )

from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.rest.routers.notifications as notif
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.middleware.path_identity import require_path_identity_owner


# ── Sentinels ────────────────────────────────────────────────────────────────────
# A fixed, valid-ISO but obviously-synthetic instant. Valid so anything that parses
# it works; fixed so an assertion can be exact; synthetic so a real `datetime.now()`
# leaking through is recognisable on sight rather than merely "a different string".
FROZEN_TIMESTAMP = "2020-02-02T02:02:02-05:00"

# A default authenticated user. Several endpoints do `uuid.UUID(authenticated_user_id)`
# and 400 on failure, so the default must be a well-formed UUID or every happy-path
# test fails for a reason having nothing to do with the endpoint.
DEFAULT_USER_ID = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"


class UnprogrammedRepoCall( AssertionError ):
    """
    Raised when a handler calls a repo method the test never programmed.

    This is deliberately LOUD. A spy that returns None for anything lets a handler
    call the WRONG method and still look successful — the exact failure this file's
    header calls out. Program what you expect; anything else is a finding.
    """


class Call( tuple ):
    """One recorded repo/queue/websocket call: name, positional args, keyword args."""

    __slots__ = ()

    def __new__( cls, name, args, kwargs ):
        return tuple.__new__( cls, ( name, tuple( args ), dict( kwargs ) ) )

    @property
    def name( self ):
        return self[ 0 ]

    @property
    def args( self ):
        return self[ 1 ]

    @property
    def kwargs( self ):
        return self[ 2 ]

    @property
    def first( self ):
        """The first positional arg, or None when the call carried none."""
        return self[ 1 ][ 0 ] if self[ 1 ] else None

    def __repr__( self ):
        return f"Call({self[ 0 ]!r}, args={self[ 1 ]!r}, kwargs={self[ 2 ]!r})"


class Spy:
    """
    A recording double whose unprogrammed methods RAISE rather than return None.

    Requires:
        - method names programmed via returns()/raises() before the handler runs

    Ensures:
        - every attribute access that is called appends a Call to .calls
        - a programmed name returns its value (or raises its exception)
        - an unprogrammed name raises UnprogrammedRepoCall, naming what was reached
        - lenient=True restores the permissive "return None" behaviour for the rare
          test that genuinely does not care what a collaborator returns
    """

    def __init__( self, label="repo", lenient=False ):
        self._label    = label
        self._lenient  = lenient
        self._returns  = {}
        self._raises   = {}
        self._sequence = {}
        self.calls     = []

    # ── programming ──────────────────────────────────────────────────────────────
    def strict( self ):
        """
        Make unprogrammed calls RAISE (the default for the repo spy).

        Worth flipping on the queue/websocket spies whenever the collaborator IS the
        subject — a lenient double returning None lets a handler reach for the wrong
        method and still produce a plausible envelope.
        """
        self._lenient = False
        return self

    def lenient( self ):
        """Make unprogrammed calls return None — for a genuinely incidental double."""
        self._lenient = True
        return self

    def returns( self, name, value ):
        """Program `name` to return `value` on every call. Chainable."""
        self._returns[ name ] = value
        return self

    def returns_in_order( self, name, *values ):
        """
        Program `name` to return each value in turn.

        For an endpoint that calls one method twice and must be shown to use BOTH
        answers — identical return values cannot distinguish "read it twice" from
        "read it once and reused it".
        """
        self._sequence[ name ] = list( values )
        return self

    def raises( self, name, exc ):
        """Program `name` to raise `exc` (an exception instance or class)."""
        self._raises[ name ] = exc
        return self

    # ── recording ────────────────────────────────────────────────────────────────
    def __getattr__( self, name ):
        if name.startswith( "_" ):
            raise AttributeError( name )

        def _recorder( *args, **kwargs ):
            self.calls.append( Call( name, args, kwargs ) )
            if name in self._raises:
                exc = self._raises[ name ]
                raise exc() if isinstance( exc, type ) else exc
            if name in self._sequence:
                seq = self._sequence[ name ]
                if not seq:
                    raise UnprogrammedRepoCall(
                        f"{self._label}.{name} was called more times than "
                        f"returns_in_order() supplied values for" )
                return seq.pop( 0 )
            if name in self._returns:
                return self._returns[ name ]
            if self._lenient:
                return None
            raise UnprogrammedRepoCall(
                f"{self._label}.{name}{args!r} was called but never programmed — "
                f"program it with .returns()/.raises(), or if reaching it is itself "
                f"the defect, that is the finding. Programmed: "
                f"{sorted( set( self._returns ) | set( self._raises ) | set( self._sequence ) )!r}" )

        return _recorder

    # ── reading ──────────────────────────────────────────────────────────────────
    @property
    def names( self ):
        """The method names called, in order, with repeats preserved."""
        return [ c.name for c in self.calls ]

    def call_to( self, name ):
        """
        The single Call to `name`. Fails if it was not called exactly once.

        "The first call to X" hides a second one; this refuses to.
        """
        hits = [ c for c in self.calls if c.name == name ]
        assert len( hits ) == 1, (
            f"expected exactly one call to {self._label}.{name}, saw {len( hits )} "
            f"(all calls: {self.names!r})" )
        return hits[ 0 ]

    def calls_to( self, name ):
        """Every Call to `name`, in order."""
        return [ c for c in self.calls if c.name == name ]

    def assert_only_called( self, *names ):
        """
        Assert the spy saw exactly these calls, in this order.

        The load-bearing form for a PURE-READ claim: an endpoint that must not write
        runs identical lines whether it writes or not, so only naming the whole call
        list catches an added write.
        """
        assert self.names == list( names ), (
            f"expected {self._label} calls {list( names )!r}, saw {self.names!r}" )

    def assert_never_called( self, *names ):
        """Assert none of `names` was reached."""
        reached = [ n for n in names if n in self.names ]
        assert not reached, (
            f"{self._label} must not reach {reached!r}, but did (all: {self.names!r})" )


class ConfigStub:
    """
    A stand-in for `lupin_app.main.config_mgr`.

    Unprogrammed keys return the caller's own `default`, which is what makes an
    un-stubbed unit context survivable. Program a key when the test's claim depends
    on the value — then a handler reading a DIFFERENT key gets the default and the
    assertion fails, which is the whole point.
    """

    def __init__( self ):
        self._values = {}
        self.reads   = []

    def set( self, key, value ):
        self._values[ key ] = value
        return self

    def get( self, key, default=None, **_kwargs ):
        self.reads.append( key )
        return self._values.get( key, default )


class _StubConfigurationManager:
    """
    Stands in for a locally-constructed `ConfigurationManager`.

    Four of the history handlers do NOT read `lupin_app.main.config_mgr` — they build
    their own ConfigurationManager inside the function and ask it for the app timezone,
    then serialise every timestamp through it. Left real, that reads the INI off disk
    and makes assertions depend on whatever timezone the machine is configured for.

    The default is UTC so a serialised timestamp is exactly reproducible. Set a
    non-zero-offset zone when the claim is that a stamp was actually CONVERTED — under
    UTC a converted and an unconverted stamp are the same string.
    """

    timezone_name = "UTC"

    def __init__( self, *_args, **_kwargs ):
        pass

    def get( self, key, default=None, **_kwargs ):
        if key == "app timezone":
            return type( self ).timezone_name
        return default


class _DbSession:
    """A unique, inert stand-in for a SQLAlchemy session."""

    def __repr__( self ):
        return f"<harness db session {id( self ):#x}>"


class Harness:
    """
    Everything an endpoint test needs, already wired.

    Attributes:
        client        TestClient over a FastAPI app carrying only the notifications router
        repo          Spy standing in for NotificationRepository (strict by default)
        queue         Spy standing in for the notification queue dependency (lenient)
        ws            Spy standing in for the websocket manager dependency (lenient)
        config        ConfigStub behind lupin_app.main.config_mgr
        sessions      every session object the get_db stub handed out, in order
        repo_built_on every session a NotificationRepository was constructed with
    """

    def __init__( self, client, repo, queue, ws, config, sessions, repo_built_on, state ):
        self.client        = client
        self.repo          = repo
        self.queue         = queue
        self.ws            = ws
        self.config        = config
        self.sessions      = sessions
        self.repo_built_on = repo_built_on
        self._state        = state

    # ── auth ─────────────────────────────────────────────────────────────────────
    @property
    def user_id( self ):
        return self._state[ "user_id" ]

    def as_user( self, user_id ):
        """
        Authenticate subsequent requests as `user_id`.

        Pass a deliberately malformed value to exercise the `uuid.UUID(...)` → 400
        guard several endpoints carry.
        """
        self._state[ "user_id" ] = user_id
        return self

    # ── config ───────────────────────────────────────────────────────────────────
    def set_app_timezone( self, timezone_name ):
        """Set the timezone the locally-built ConfigurationManager reports (default UTC)."""
        _StubConfigurationManager.timezone_name = timezone_name
        return self

    # ── db ───────────────────────────────────────────────────────────────────────
    def fail_db( self, exc=None ):
        """
        Make `get_db()` itself raise, i.e. the connection is down.

        Distinct from `repo.raises(...)`: this is a fault BEFORE any repo method is
        reached, which is the shape that must not be reported as "no such row".
        """
        self._state[ "db_error" ] = exc or RuntimeError( "connection reset" )
        return self

    # ── assertions worth sharing ─────────────────────────────────────────────────
    def assert_repo_built_on_the_open_session( self ):
        """
        Assert every NotificationRepository was constructed with a session the
        `get_db` context manager actually handed out — not a stale or invented one.
        """
        assert self.repo_built_on, "no NotificationRepository was constructed at all"
        stray = [ s for s in self.repo_built_on if s not in self.sessions ]
        assert not stray, (
            f"a repository was built on {stray!r}, which get_db never yielded" )


def build_harness( monkeypatch, strict_repo=True ):
    """
    Wire a notifications-router harness onto `monkeypatch` and return it.

    Requires:
        - monkeypatch is a live pytest MonkeyPatch (function-scoped)

    Ensures:
        - returns a Harness whose .client speaks to the notifications router only
        - auth is overridden; the request user is DEFAULT_USER_ID until as_user()
        - the path-owner check is overridden to admit any path user
        - get_db(), NotificationRepository, get_local_timestamp are stubbed
        - lupin_app.main config_mgr/app_debug/app_verbose/queue/ws are stubbed
        - the router's two module-level idempotency caches are emptied both now and
          on teardown, so one test's key cannot silently answer another's request
        - every patch is undone by monkeypatch at teardown

    Raises:
        - nothing; a misuse surfaces as a failing assertion inside a test
    """
    state = { "user_id": DEFAULT_USER_ID, "db_error": None }

    repo   = Spy( "repo",  lenient=not strict_repo )
    queue  = Spy( "queue", lenient=True )
    ws     = Spy( "ws",    lenient=True )
    config = ConfigStub()

    # The notify path reads three DICTS off the websocket manager for its offline
    # diagnostics, not methods. Real attributes are set here so an attribute access
    # finds a mapping instead of falling through to the recorder factory, which would
    # hand back a function and blow up on `.get(...)`.
    ws.user_sessions      = {}
    ws.active_connections = {}
    ws.user_to_email      = {}

    sessions      = []
    repo_built_on = []

    # ── lupin_app.main: the trap named in this module's header ───────────────────
    import lupin_app.main as main_module
    monkeypatch.setattr( main_module, "config_mgr",              config, raising=False )
    monkeypatch.setattr( main_module, "app_debug",               False,  raising=False )
    monkeypatch.setattr( main_module, "app_verbose",             False,  raising=False )
    monkeypatch.setattr( main_module, "jobs_notification_queue", queue,  raising=False )
    monkeypatch.setattr( main_module, "websocket_manager",       ws,     raising=False )

    # ── the timestamp: fixed, so an envelope's value is assertable ───────────────
    monkeypatch.setattr( notif, "get_local_timestamp", lambda: FROZEN_TIMESTAMP )

    # ── the OTHER config door: a locally-built ConfigurationManager ──────────────
    # Patched on its DEFINING module, because the handlers import it inside the
    # function body — patching the router's namespace leaves the real one running.
    import cosa.config.configuration_manager as cfg_module
    monkeypatch.setattr( cfg_module, "ConfigurationManager", _StubConfigurationManager )
    monkeypatch.setattr( _StubConfigurationManager, "timezone_name", "UTC" )

    # ── the db seam ──────────────────────────────────────────────────────────────
    class _Ctx:
        def __enter__( self ):
            if state[ "db_error" ] is not None:
                raise state[ "db_error" ]
            session = _DbSession()
            sessions.append( session )
            return session

        def __exit__( self, *_exc ):
            return False

    def _get_db():
        return _Ctx()

    def _make_repo( session ):
        repo_built_on.append( session )
        return repo

    monkeypatch.setattr( notif, "get_db",                 _get_db )
    monkeypatch.setattr( notif, "NotificationRepository", _make_repo )

    # ── module-level caches: shared mutable state across tests ───────────────────
    # Both are module-level OrderedDicts with a 60s TTL, so without this a key minted
    # by one test is still live for the next one in the same second — and an
    # idempotency HIT looks exactly like a successful fresh call.
    notif._idempotency_cache.clear()
    notif._ask_idempotency_index.clear()
    monkeypatch.setattr( notif, "_idempotency_cache",     type( notif._idempotency_cache )() )
    monkeypatch.setattr( notif, "_ask_idempotency_index", type( notif._ask_idempotency_index )() )

    # ── the app ──────────────────────────────────────────────────────────────────
    app = FastAPI()
    app.include_router( notif.router )
    app.dependency_overrides[ require_api_key_or_jwt ]    = lambda: state[ "user_id" ]
    # The path-owner check (row d90baf3d) is stood down here, because these files test what a handler
    # DOES with a path user, and they write arbitrary users into paths. Whether a caller may name
    # that user is pinned in test_notification_routes_refuse_another_users_path.py, over no override.
    app.dependency_overrides[ require_path_identity_owner ] = lambda: state[ "user_id" ]
    app.dependency_overrides[ notif.get_notification_queue ] = lambda: queue
    app.dependency_overrides[ notif.get_websocket_manager ]  = lambda: ws

    client = TestClient( app, raise_server_exceptions=False )

    return Harness( client, repo, queue, ws, config, sessions, repo_built_on, state )


def make_harness_fixture( name="harness", strict_repo=True ):
    """
    Build the pytest fixture a test file installs with one line.

    Requires:
        - the returned object is bound at module scope in the test file

    Ensures:
        - the fixture is function-scoped; every test gets a fresh app, spy and cache
        - the TestClient is closed and every patch undone before the next test

    Example:
        harness = make_harness_fixture()
    """

    @pytest.fixture( name=name )
    def _fixture( monkeypatch ):
        h = build_harness( monkeypatch, strict_repo=strict_repo )
        with h.client:
            yield h

    return _fixture


def assert_no_accidental_500( response ):
    """
    Fail loudly when a response is a 500 carrying the un-stubbed-config signature.

    The router converts any stray exception into a 500 with the exception text in
    `detail`, so a missing `config_mgr` stub reads as an ordinary server error. A test
    expecting a 200 already fails; a test expecting an ERROR passes for the wrong
    reason. Call this in the error tests to keep the two apart.
    """
    if response.status_code != 500:
        return
    detail = ""
    try:
        detail = str( response.json().get( "detail", "" ) )
    except Exception:  # pragma: no cover - a non-JSON 500 carries no signature to read
        return
    assert "config_mgr" not in detail and "app_debug" not in detail, (
        f"this 500 is the harness, not the endpoint — lupin_app.main was not stubbed: "
        f"{detail!r}" )


def a_uuid( tag ):
    """
    A deterministic, DISTINCT uuid string carrying a readable tag.

    Every id in a test should differ, so "the right row" is never satisfied by "any
    row". `a_uuid( "asked" )` and `a_uuid( "answered" )` are stable across runs and
    never collide.
    """
    return str( uuid.uuid5( uuid.NAMESPACE_URL, f"lupin-notif-harness/{tag}" ) )
