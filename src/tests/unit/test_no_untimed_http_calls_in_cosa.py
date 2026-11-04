"""
Every outbound HTTP call in src/cosa/ carries a timeout — row f6ce66f1 (split from abe4188d).

THE SHAPE: `requests` has NO default timeout, `aiohttp.ClientSession()` defaults to a five-minute
total, and `urllib.request.urlopen` has none either, so one wedged peer hangs the calling thread
forever and the failure looks like "the server stopped answering", not like a missing argument.

MEASURED 2026-09-30 at 8420e8b0a by an AST census (not a text grep, so multi-line calls and the
`import requests as http_requests` alias in swe_team/orchestrator.py are read): 18 requests and
ClientSession sites, plus 3 urlopen sites. The nine untimed sites the row listed already carried
timeouts at that sha, and the two bare `aiohttp.ClientSession()` in rest/routers/peer.py were the
only untimed ones left; they now carry a session-level default. Literal numbers were also moved
to named module constants, and this guard holds that line.

WHAT THE GUARD REQUIRES of each call to `requests.<verb>`, `requests.Session()`, `aiohttp.ClientSession(...)`
and `urlopen(...)`:
  - a `timeout=` keyword is present
  - its value is not the literal `None` (which is unbounded) and not a bare number — a named
    constant, a config read or a variable, so the bound has a name someone can find and change
  - no `**kwargs` standing in for it (unverifiable, so refused)
`requests.Session()` is refused outright: it has no timeout parameter, so each of its calls would
need checking by hand.

⚠️ TRAP NOTED IN THE ROW, AND NOT CHECKED HERE: `requests.exceptions.Timeout` is not a TimeoutError
subclass (Timeout -> RequestException -> OSError), so adding a timeout= changes what a caller's
except clause must catch. This guard asserts the bound exists, not that its caller handles the
exception. The 15 current requests sites were read: all sit inside handlers naming Timeout,
RequestException or Exception, except the two helpers whose callers own the handling.

OUT OF SCOPE, stated so a zero is not misread: httpx (it ships a 5s default), subprocess calls,
tests, `.venv`, and anything outside src/cosa/.

Venue: :7999-eligible. One `git ls-files` plus parsing ~900 files.
"""
import ast
import os
import subprocess

import pytest

import cosa.utils.util as cu

ROOT = cu.get_project_root()

_REQUESTS_VERBS = frozenset( { "get", "post", "put", "delete", "patch", "head", "request", "options" } )

# Files KNOWN to hold guarded call sites — the positive control. A scan that stops finding these
# has gone blind, and an empty scan passes every assertion in it.
_EXPECTED_SITE_FILES = frozenset( {
    "src/cosa/agents/llm_completion.py",               # requests.post + aiohttp.ClientSession
    "src/cosa/agents/swe_team/orchestrator.py",        # `import requests as http_requests` alias
    "src/cosa/agents/model_window.py",                 # urllib.request.urlopen
    "src/cosa/rest/routers/peer.py",                   # bare-session defaults
} )


def cosa_python_files( root ):
    """
    Requires: root is a git checkout
    Ensures:  returns tracked .py files under src/cosa, minus tests and vendored venvs, sorted
    """
    out = subprocess.run( [ "git", "ls-files", "-z", "--", "src/cosa" ], cwd=root,
                          capture_output=True, check=True ).stdout
    paths = [ p.decode() for p in out.split( b"\0" ) if p ]
    return sorted( p for p in paths
                   if p.endswith( ".py" ) and "/tests/" not in p and "/.venv/" not in p )


def _dotted( node ):
    """'urllib.request.urlopen' for an Attribute chain / Name, else None."""
    parts = []
    while isinstance( node, ast.Attribute ):
        parts.append( node.attr ); node = node.value
    if isinstance( node, ast.Name ):
        parts.append( node.id )
        return ".".join( reversed( parts ) )
    return None


def find_calls( source ):
    """
    Requires: source is Python source text
    Ensures:  returns [ ( lineno, kind, problem_or_None ) ] for every guarded HTTP call,
              problem is None when the call is bounded by a named/computed timeout
    """
    tree = ast.parse( source )
    requests_names, aiohttp_names, direct = set(), set(), {}
    for node in ast.walk( tree ):
        if isinstance( node, ast.Import ):
            for alias in node.names:
                bound = alias.asname or alias.name.split( "." )[ 0 ]
                if alias.name == "requests":           requests_names.add( bound )
                if alias.name == "aiohttp":            aiohttp_names.add( bound )
                if alias.name == "urllib.request":     direct[ ( alias.asname or "urllib.request" ) + ".urlopen" ] = "urlopen"
        elif isinstance( node, ast.ImportFrom ):
            for alias in node.names:
                bound = alias.asname or alias.name
                if node.module == "requests" and alias.name in _REQUESTS_VERBS: direct[ bound ] = "requests." + alias.name
                if node.module == "requests" and alias.name == "Session":       direct[ bound ] = "requests.Session"
                if node.module == "aiohttp" and alias.name == "ClientSession":  direct[ bound ] = "aiohttp.ClientSession"
                if node.module == "urllib.request" and alias.name == "urlopen": direct[ bound ] = "urlopen"

    found = []
    for node in ast.walk( tree ):
        if not isinstance( node, ast.Call ):
            continue
        name = _dotted( node.func )
        kind = None
        if name in direct:
            kind = direct[ name ]
        elif name is not None and "." in name:
            head, attr = name.rsplit( ".", 1 )
            if head in requests_names and attr in _REQUESTS_VERBS:       kind = "requests." + attr
            elif head in requests_names and attr in ( "Session", "session" ): kind = "requests.Session"
            elif head in aiohttp_names and attr == "ClientSession":      kind = "aiohttp.ClientSession"
        if kind is None:
            continue

        if kind == "requests.Session":
            found.append( ( node.lineno, kind, "requests.Session() has no timeout parameter — use a verb call with timeout=" ) )
            continue
        timeout = [ k for k in node.keywords if k.arg == "timeout" ]
        if not timeout:
            splat = any( k.arg is None for k in node.keywords )
            found.append( ( node.lineno, kind, "**kwargs may hide the timeout — pass timeout= explicitly" if splat
                            else "no timeout= — this call can hang forever" ) )
            continue
        value = timeout[ 0 ].value
        if isinstance( value, ast.Constant ) and value.value is None:
            found.append( ( node.lineno, kind, "timeout=None is unbounded" ) )
        elif isinstance( value, ast.Constant ):
            found.append( ( node.lineno, kind, f"bare timeout literal {value.value!r} — use a named constant or a config read" ) )
        else:
            found.append( ( node.lineno, kind, None ) )
    return sorted( found )


def scan( root ):
    """Returns ( violations, sites, files_with_sites ) over the real tracked population."""
    violations, sites, files = [], 0, set()
    for rel in cosa_python_files( root ):
        with open( os.path.join( root, rel ), encoding="utf-8" ) as fh:
            calls = find_calls( fh.read() )
        if calls:
            files.add( rel )
        for lineno, kind, problem in calls:
            sites += 1
            if problem:
                violations.append( ( rel, lineno, kind, problem ) )
    return violations, sites, files


def test_every_http_call_in_cosa_is_bounded():
    violations, sites, files = scan( ROOT )
    print( f"\n[untimed-http scan] tracked .py scanned={len( cosa_python_files( ROOT ) )} guarded sites={sites} files-with-sites={len( files )}" )

    assert sites > 0, "the scan found no HTTP call sites at all — it would pass forever watching nothing"
    missing = sorted( _EXPECTED_SITE_FILES - files )
    assert not missing, f"the scan no longer sees call sites in {missing} — it has gone blind there"
    assert not violations, "unbounded HTTP calls:\n" + "\n".join(
        f"  {rel}:{line}  {kind}  {problem}" for rel, line, kind, problem in violations )


# ── the scanner must be able to find each defect ─────────────────────────────

@pytest.mark.parametrize( "source,fragment", [
    ( "import requests\nrequests.post( u )\n",                                   "no timeout" ),
    ( "import requests\nrequests.get(\n    u,\n    headers=h,\n)\n",             "no timeout" ),
    ( "import requests as http_requests\nhttp_requests.post( u, json=b )\n",      "no timeout" ),
    ( "from requests import post\npost( u )\n",                                   "no timeout" ),
    ( "import requests\nrequests.get( u, **kw )\n",                               "**kwargs" ),
    ( "import requests\nrequests.get( u, timeout=None )\n",                       "unbounded" ),
    ( "import requests\nrequests.get( u, timeout=30 )\n",                         "bare timeout literal" ),
    ( "import requests\ns = requests.Session()\n",                                "no timeout parameter" ),
    ( "import aiohttp\nasync def f():\n    async with aiohttp.ClientSession() as s: pass\n", "no timeout" ),
    ( "from aiohttp import ClientSession\nClientSession()\n",                     "no timeout" ),
    ( "import urllib.request\nurllib.request.urlopen( u )\n",                     "no timeout" ),
    ( "from urllib.request import urlopen\nurlopen( u )\n",                       "no timeout" ),
] )
def test_each_defect_shape_is_found( source, fragment ):
    problems = [ p for _l, _k, p in find_calls( source ) if p ]
    assert len( problems ) == 1 and fragment in problems[ 0 ], problems


@pytest.mark.parametrize( "source", [
    "import requests\nrequests.post( u, timeout=_T )\n",
    "import requests\nrequests.post( u, timeout=self._remaining( d ) )\n",
    "import requests\nrequests.get( u, timeout=cfg.timeout )\n",
    "import aiohttp\naiohttp.ClientSession( timeout=aiohttp.ClientTimeout( total=_T ) )\n",
    "import urllib.request\nurllib.request.urlopen( u, timeout=t )\n",
    "import requests\nsession.get( u )\n",           # a non-requests receiver is not this guard's business
    "import requests\nfoo( u )\n",
] )
def test_bounded_or_unrelated_calls_are_not_flagged( source ):
    assert [ p for _l, _k, p in find_calls( source ) if p ] == []


def test_a_call_site_reports_its_line_and_kind():
    assert find_calls( "import requests\n\nrequests.get( u )\n" ) == [ ( 3, "requests.get", "no timeout= — this call can hang forever" ) ]


def test_population_is_git_tracked_python_minus_tests_and_venvs():
    files = cosa_python_files( ROOT )
    assert files and all( f.startswith( "src/cosa/" ) and f.endswith( ".py" ) for f in files )
    assert not any( "/tests/" in f or "/.venv/" in f for f in files )
    assert "src/cosa/agents/llm_completion.py" in files
