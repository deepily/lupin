"""
Shared harness for testing operator scripts under `src/scripts/`.

WHY THIS EXISTS, AND WHICH FILE FIRST NEEDED IT. `src/scripts/probe_cc_bounded_billing.py`
is the file that forced it (row `2b2f426e`, costed 2026-08-30). Pricing that file's
tests split the estimate in two and showed the FIXTURE was roughly half the total clock
while amortising over exactly one file. Twenty-one other untested scripts share the
same three obstacles, so the fixture was lifted out here rather than written once and
thrown away. Mr Radio ruled the harness separate work so its cost is not folded into
that file's cover-or-exempt decision.

THE THREE OBSTACLES, all measured on the billing probe and all shared by the family:

1. 🔴 CONFIGURATION IS READ AT IMPORT TIME. Operator scripts assign module-level
   constants from `os.environ` — `EMAIL = os.environ.get( ... )` at line 45 of the
   probe. By the time a test can monkeypatch anything, the module already holds `None`.
   `import_script()` applies the environment FIRST and imports after, so the constants
   come out holding what the test asked for.

2. 🔴 THE NETWORK CALLS ARE MODULE-LEVEL `requests` USE. Scripts call `requests.post` /
   `requests.get` directly rather than through an injectable client, so the seam is the
   `requests` name inside the imported module.

3. 🔴 THE PACING IS REAL. The probe carries four `time.sleep( 60 )` calls and a poll
   loop with a 240-second cap. An unstubbed `main()` sleeps over ten minutes PER TEST,
   which is the difference between a suite that runs and one nobody runs.

🔴 THE DESIGN RULE EVERY DEFAULT FOLLOWS — make the WRONG answer a DIFFERENT answer:

  - the HTTP double is STRICT. An unprogrammed URL RAISES rather than returning a
    plausible empty 200, so a script posting to the wrong door fails loudly instead of
    quietly receiving nothing. That matters most in this family: these scripts talk to
    a live server, and a retired endpoint answering 410 is the exact class of defect
    several of them exist to catch.
  - sleeps are RECORDED, not merely skipped. Deleting a `sleep( 60 )` from a
    rate-limited probe is a real defect that a silently-skipping stub would hide — a
    test can assert the pacing was REQUESTED even though none of it elapsed.
  - every call must carry `timeout=`. An operator script without one hangs forever
    against a wedged server, and that is invisible to any assertion about the response.
  - `import_script()` returns a FRESH module each call, so one test's mutated
    module-level state cannot answer another test's question.

USAGE:

    from tests.helpers.script_probe_harness import script_harness   # noqa: F401

    def test_it_posts_to_the_v2_door( script_harness ):
        h = script_harness
        h.env( LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL="a@b.c" )
        h.http.post( "/api/v2/submit", json={ "id": "JOB-1" } )
        mod = h.import_script( "probe_cc_bounded_billing" )
        assert mod.EMAIL == "a@b.c"
"""

import importlib
import os
import sys

import pytest

# Bootstrap: mirror the unit-tier import bootstrap so this module is importable
# whether or not the caller already inserted src/ on the path.
_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root:
    _src_path = os.path.join( _lupin_root, "src" )
    if _src_path not in sys.path:
        sys.path.insert( 0, _src_path )


class UnprogrammedRequest( AssertionError ):
    """
    Raised when a script makes an HTTP call the test never programmed.

    Deliberately loud. A double answering every URL with an empty 200 would let a
    script post to a retired endpoint and still look healthy — and catching exactly
    that is why several of these scripts exist.
    """


class Response:
    """
    A stand-in for `requests.Response` covering what operator scripts actually read.

    Requires:
        - status_code is an int; json_body is JSON-serialisable or None

    Ensures:
        - .json() returns the body, or raises ValueError when there is none — which is
          what a real Response does for a non-JSON body, so a script's own error
          handling is exercised rather than bypassed
        - .ok mirrors requests' rule (status < 400)
        - .raise_for_status() raises on 4xx/5xx and returns None otherwise
    """

    def __init__( self, status_code=200, json_body=None, text=None ):
        self.status_code = status_code
        self._json       = json_body
        self.text        = text if text is not None else ( "" if json_body is None else str( json_body ) )

    @property
    def ok( self ):
        return self.status_code < 400

    def json( self ):
        if self._json is None:
            raise ValueError( "no JSON object could be decoded" )
        return self._json

    def raise_for_status( self ):
        if self.status_code >= 400:
            raise RuntimeError( f"HTTP {self.status_code}" )

    def __repr__( self ):
        return f"<Response {self.status_code} json={self._json!r}>"


class Call( tuple ):
    """One recorded HTTP call: method, url, kwargs."""

    __slots__ = ()

    def __new__( cls, method, url, kwargs ):
        return tuple.__new__( cls, ( method, url, dict( kwargs ) ) )

    @property
    def method( self ):
        return self[ 0 ]

    @property
    def url( self ):
        return self[ 1 ]

    @property
    def kwargs( self ):
        return self[ 2 ]

    def __repr__( self ):
        return f"Call({self[ 0 ]} {self[ 1 ]} {self[ 2 ]!r})"


class HttpDouble:
    """
    A strict, recording stand-in for the `requests` module.

    Program a URL with post()/get(); an unprogrammed URL raises UnprogrammedRequest.
    Matching is by EXACT url first, then by longest registered SUFFIX — so a test can
    pin `/api/v2/submit` without restating the base URL, while two doors differing only
    in their path stay distinguishable.
    """

    def __init__( self ):
        self.calls            = []
        self._routes          = {}
        self.timeout_required = True

    # ── programming ──────────────────────────────────────────────────────────────
    def post( self, url, status_code=200, json=None, text=None, responses=None ):
        """Program POST `url`. `responses` gives a SEQUENCE, for a polled endpoint."""
        return self._route( "POST", url, status_code, json, text, responses )

    def get( self, url, status_code=200, json=None, text=None, responses=None ):
        """Program GET `url`. `responses` gives a SEQUENCE, for a polled endpoint."""
        return self._route( "GET", url, status_code, json, text, responses )

    def _route( self, method, url, status_code, json, text, responses ):
        if responses is not None:
            self._routes[ ( method, url ) ] = list( responses )
        else:
            self._routes[ ( method, url ) ] = [ Response( status_code, json, text ) ]
        return self

    def fail( self, method, url, exc ):
        """Program `url` to RAISE — a connection error rather than an HTTP status."""
        self._routes[ ( method.upper(), url ) ] = exc
        return self

    # ── the seam the script sees ─────────────────────────────────────────────────
    def _dispatch( self, method, url, **kwargs ):
        self.calls.append( Call( method, url, kwargs ) )

        if self.timeout_required and "timeout" not in kwargs:
            raise UnprogrammedRequest(
                f"{method} {url} was made with no timeout= — an operator script "
                f"without one hangs forever against a wedged server. Set "
                f"harness.http.timeout_required = False only if that is deliberate." )

        entry = self._match( method, url )
        if entry is None:
            raise UnprogrammedRequest(
                f"{method} {url} was called but never programmed. Programmed routes: "
                f"{sorted( f'{m} {u}' for m, u in self._routes )!r}" )

        if isinstance( entry, BaseException ):
            raise entry
        if isinstance( entry, type ) and issubclass( entry, BaseException ):
            raise entry()

        if len( entry ) == 1:
            return entry[ 0 ]
        if not entry:
            raise UnprogrammedRequest(
                f"{method} {url} was called more times than its programmed sequence "
                f"supplied responses for" )
        return entry.pop( 0 )

    def _match( self, method, url ):
        exact = self._routes.get( ( method, url ) )
        if exact is not None:
            return exact
        candidates = [ ( m, u ) for ( m, u ) in self._routes
                       if m == method and url.endswith( u ) ]
        if not candidates:
            return None
        return self._routes[ max( candidates, key=lambda k: len( k[ 1 ] ) ) ]

    # ── reading ──────────────────────────────────────────────────────────────────
    @property
    def urls( self ):
        """Every ( method, url ) called, in order, repeats preserved."""
        return [ ( c.method, c.url ) for c in self.calls ]

    def calls_to( self, method, url_suffix ):
        return [ c for c in self.calls
                 if c.method == method.upper() and c.url.endswith( url_suffix ) ]

    def call_to( self, method, url_suffix ):
        """The single call to this endpoint. Fails if it was not made exactly once."""
        hits = self.calls_to( method, url_suffix )
        assert len( hits ) == 1, (
            f"expected exactly one {method.upper()} to *{url_suffix}, saw {len( hits )} "
            f"(all calls: {self.urls!r})" )
        return hits[ 0 ]

    def assert_never_called( self, method, url_suffix ):
        hits = self.calls_to( method, url_suffix )
        assert not hits, (
            f"{method.upper()} *{url_suffix} must not be reached, but was, {len( hits )}x" )


class SleepRecorder:
    """
    A `time.sleep` stand-in that RECORDS instead of elapsing.

    Recording rather than silently skipping is the point: deleting a `sleep( 60 )` from
    a rate-limited probe is a real defect, and a stub that merely made the tests fast
    would hide it. `total` lets a test assert the pacing a script INTENDED.
    """

    def __init__( self ):
        self.durations = []

    def __call__( self, seconds ):
        self.durations.append( seconds )

    @property
    def total( self ):
        return sum( self.durations )

    @property
    def count( self ):
        return len( self.durations )


class _RequestsFacade:
    """The subset of the `requests` module surface operator scripts use."""

    def __init__( self, double ):
        self._double = double

    def post( self, url, **kwargs ):
        return self._double._dispatch( "POST", url, **kwargs )

    def get( self, url, **kwargs ):
        return self._double._dispatch( "GET", url, **kwargs )

    def put( self, url, **kwargs ):
        return self._double._dispatch( "PUT", url, **kwargs )

    def delete( self, url, **kwargs ):
        return self._double._dispatch( "DELETE", url, **kwargs )


def project_root():
    """
    Resolve the repo root from LUPIN_ROOT, falling back to this file's own location.

    ⚠️ THE ENV VAR WINS, AND IN A WORKTREE IT USUALLY NAMES THE MAIN CHECKOUT. A test
    importing a script through this harness from a worktree without exporting
    LUPIN_ROOT="$PWD" would read the MAIN tree's copy of that script — the same defect
    that let `purge-pycache.sh` purge the wrong tree (measured 2026-08-30). The unit
    tier's own conftest makes the same assumption, so this is consistent rather than a
    new requirement, but it is stated here because it is silent when wrong.
    """
    root = os.environ.get( "LUPIN_ROOT" )
    if root:
        return root
    return os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )


class ScriptHarness:
    """
    Import an operator script under a controlled environment, network and clock.

    Attributes:
        http    HttpDouble standing in for `requests`
        sleeps  SleepRecorder standing in for `time.sleep`
    """

    SCRIPTS_DIR = "src/scripts"

    def __init__( self, monkeypatch, scripts_dir=None ):
        """
        `scripts_dir` overrides where scripts are imported from. It exists so this
        harness can be tested against a synthetic script in a tmp dir rather than
        against a real operator script — a harness that cannot be proven to
        discriminate is worse than no harness, and the only honest proof needs a file
        whose behaviour the test controls.
        """
        self._monkeypatch = monkeypatch
        self.http         = HttpDouble()
        self.sleeps       = SleepRecorder()
        self._env         = {}
        self.imported     = []
        self._scripts_dir = scripts_dir

    # ── environment ──────────────────────────────────────────────────────────────
    def env( self, **values ):
        """
        Stage environment values to be applied BEFORE the script is imported.

        This is the whole reason the harness exists: these scripts assign module-level
        constants from os.environ at import time, so a value set afterwards is set too
        late to be read.
        """
        self._env.update( values )
        return self

    def unset( self, *names ):
        """Stage names to be ABSENT at import — for the missing-credential path."""
        for name in names:
            self._env[ name ] = None
        return self

    # ── import ───────────────────────────────────────────────────────────────────
    def import_script( self, module_name ):
        """
        Import `src/scripts/<module_name>.py` fresh, under the staged environment,
        a strict HTTP double and a recording clock.

        Requires:
            - module_name names a module under src/scripts (no .py, no path)

        Ensures:
            - the environment is applied BEFORE the module body runs
            - a FRESH module each call, so module-level state from one test cannot
              answer another test's question
            - `requests` and `time.sleep` inside the module are the harness's doubles

        Raises:
            - ModuleNotFoundError if no such script exists under src/scripts
        """
        scripts_dir = self._scripts_dir or os.path.join( project_root(), self.SCRIPTS_DIR )
        if scripts_dir not in sys.path:
            self._monkeypatch.syspath_prepend( scripts_dir )

        for name, value in self._env.items():
            if value is None:
                self._monkeypatch.delenv( name, raising=False )
            else:
                self._monkeypatch.setenv( name, value )

        # A previously-imported copy carries another test's constants, so it is evicted
        # rather than handed back.
        sys.modules.pop( module_name, None )
        module = importlib.import_module( module_name )
        self._monkeypatch.setitem( sys.modules, module_name, module )
        self.imported.append( module_name )

        self._monkeypatch.setattr( module, "requests", _RequestsFacade( self.http ),
                                   raising=False )
        if hasattr( module, "time" ):
            self._monkeypatch.setattr( module.time, "sleep", self.sleeps, raising=False )
        return module


@pytest.fixture
def script_harness( monkeypatch ):
    """
    Function-scoped harness for an operator script under src/scripts.

    Ensures:
        - every patch is undone by monkeypatch at teardown
        - each test gets a fresh HTTP double, clock and module
    """
    return ScriptHarness( monkeypatch )
