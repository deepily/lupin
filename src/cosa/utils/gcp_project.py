#!/usr/bin/env python3
"""
Resolve the GCP project id (and Vertex location) for Python callers.

WHY THIS EXISTS. Rick, 2026-08-16: *"you're not supposed to use an API key for Gemini, you're
supposed to use the project ID which I gave you in an environment variable."* The variable is
`LUPIN_GCP_PROJECT_ID` — and a Python process cannot count on it being set:

  - `~/.bashrc:138` exports it, but `.bashrc` only runs for INTERACTIVE shells. systemd units, cron
    jobs, hooks, test runners and containers all start without it. Measured: `env -i bash -c` shows
    it unset, an interactive login shell shows the value.
  - `src/scripts/cloud-run.env` also carries it, but that file is a SHELL file and git-ignored
    (`.gitignore:74`) — nothing in Python reads it, and a fresh clone or rebuilt container does not
    even have it. The committed template is `cloud-run.env.example`.

So "read os.environ and hope" silently resolves to nothing, or worse, to a stale project. This
module gives Python the same three properties `src/scripts/cloud-run-config.sh` already has in
shell — **environment override wins, else parse the env file, else FAIL LOUDLY** — rather than
inventing a fourth convention.

WHAT IT WILL NOT DO. It never defaults, never falls back to a sandbox project, and never falls back
to an API key. An absent project id is an error, because the failure it prevents — billing or
querying the wrong project — looks like a permissions problem and costs an afternoon to diagnose.
"""

import os
import re
from pathlib import Path

PROJECT_ENV_KEY  = "LUPIN_GCP_PROJECT_ID"
LOCATION_ENV_KEY = "LUPIN_GCP_LOCATION"

# `global` serves gemini-3.1-flash-lite; us-central1 returns 404 NOT_FOUND for it (measured
# 2026-08-16). That region also carries an older scar — vertex_env.py:90-92 records rawPredict
# "genuinely 400s" there. Two APIs, two failure modes, same region.
DEFAULT_LOCATION = "global"

# KEY="value" / KEY='value' / KEY=value, with optional `export`, ignoring comments.
_ENV_LINE_RE = re.compile( r"""^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$""" )


def _default_env_file():
    """
    Requires:
        - LUPIN_ROOT is set, or the repo lives at the documented default

    Ensures:
        - returns the Path to src/scripts/cloud-run.env under the project root
        - does NOT check existence — the caller decides whether absence is fatal
    """
    root = os.environ.get( "LUPIN_ROOT", "/var/lupin" )
    return Path( root ) / "src" / "scripts" / "cloud-run.env"


def parse_env_file( path ):
    """
    Read a shell-style env file into a dict, without executing it.

    Requires:
        - path is a Path

    Ensures:
        - returns {} when the file does not exist — absence is the caller's decision to judge
        - returns a dict of KEY -> value with surrounding quotes stripped
        - comment lines and blank lines are ignored; `export` prefixes are tolerated
        - a value that is an unexpanded shell reference (e.g. "${FOO:-}") is treated as EMPTY,
          because that is what the template ships and an empty placeholder must never look like a
          configured value
    """
    if not Path( path ).exists(): return {}

    found = {}
    for line in Path( path ).read_text( encoding="utf-8" ).splitlines():
        if line.lstrip().startswith( "#" ): continue

        m = _ENV_LINE_RE.match( line )
        if not m: continue

        key, value = m.group( 1 ), m.group( 2 )
        value = value.split( " #" )[ 0 ].strip()                       # trailing comment
        if len( value ) >= 2 and value[ 0 ] == value[ -1 ] and value[ 0 ] in "\"'":
            value = value[ 1:-1 ]
        if value.startswith( "$" ): value = ""                         # unexpanded placeholder

        found[ key ] = value

    return found


def resolve_gcp_project_id( environ=None, env_file=None ):
    """
    Resolve the GCP project id.

    Requires:
        - environ is a Mapping (os.environ when None) — injectable for tests
        - env_file is a Path to a shell env file (the repo's cloud-run.env when None)

    Ensures:
        - an environment value WINS over the file, matching cloud-run-config.sh's override
          semantics — the two must not disagree about precedence
        - otherwise the value comes from the env file
        - raises RuntimeError when neither supplies a non-empty value, naming BOTH sources it
          looked at, so the reader knows what to fix rather than only that something is missing
        - NEVER returns a default and never falls back to an API key
    """
    environ  = os.environ if environ is None else environ
    env_file = _default_env_file() if env_file is None else Path( env_file )

    from_env = ( environ.get( PROJECT_ENV_KEY ) or "" ).strip()
    if from_env: return from_env

    from_file = ( parse_env_file( env_file ).get( PROJECT_ENV_KEY ) or "" ).strip()
    if from_file: return from_file

    raise RuntimeError(
        f"{PROJECT_ENV_KEY} is not set and could not be read from {env_file}. "
        f"Export it, or copy src/scripts/cloud-run.env.example to cloud-run.env and fill it in. "
        f"Note that ~/.bashrc only runs for interactive shells, so a hook, cron job, container or "
        f"test runner will not inherit it. There is no default and no API-key fallback."
    )


def resolve_gcp_location( environ=None, env_file=None ):
    """
    Resolve the Vertex location.

    Requires:
        - environ is a Mapping (os.environ when None)
        - env_file is a Path or None

    Ensures:
        - environment wins, then the env file, then DEFAULT_LOCATION
        - unlike the project id this DOES default, because "global" is a correct answer rather than
          a guess about someone's billing
    """
    environ  = os.environ if environ is None else environ
    env_file = _default_env_file() if env_file is None else Path( env_file )

    from_env = ( environ.get( LOCATION_ENV_KEY ) or "" ).strip()
    if from_env: return from_env

    from_file = ( parse_env_file( env_file ).get( LOCATION_ENV_KEY ) or "" ).strip()
    return from_file or DEFAULT_LOCATION


def quick_smoke_test():
    """Print what this box resolves, without raising on a missing project id."""
    print( "gcp_project resolution" )
    try:
        print( f"  project  : {resolve_gcp_project_id()}" )
    except RuntimeError as e:
        print( f"  project  : UNRESOLVED — {e}" )
    print( f"  location : {resolve_gcp_location()}" )


if __name__ == "__main__":
    quick_smoke_test()
