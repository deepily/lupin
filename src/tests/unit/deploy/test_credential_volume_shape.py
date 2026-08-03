"""
Pin the shape of the Claude Code OAuth credential mount on the LOCAL compose file.

WHAT THIS GUARDS (row c7c60896, ruled 2026-08-02). `docker-compose.yml` used to
bind the host's `~/.claude/.credentials.json` as a SINGLE FILE. Docker resolves a
single-file bind exactly once, at container start. Claude Code renews its access
token by REPLACING the file — write a temp, then rename — which mints a new inode.
The container keeps holding the old one and answers `401 OAuth access token has
been revoked` until somebody restarts it. The access token lives exactly 8 hours,
so that fired roughly three times a day, taking every bounded-CC path in the
container with it: podcast, deep research, BFE, TFE, presentations.

Two near-miss remedies were measured and rejected before the shape below was
chosen, and they are why this test asserts a VOLUME rather than merely "not :ro":

  - dropping `:ro` from the single-file bind — rename-over-a-bind-mounted-file
    still fails "Resource busy", so the renewal cannot land either way;
  - a host symlink pointing into a shared directory — `rename(2)` replaces the
    SYMLINK, not its target, so the first renewal silently destroys the link and
    reverts to the broken state with no error at all.

The shape that works is the one the cloud compose files have used all along: a
named volume over the whole `/home/rruiz/.claude`, holding the container's OWN
`claude /login` grant, which renews itself and survives a recreate.

WHY A DEDICATED FILE rather than more rows in test_compose_service_parity.py:
that suite asserts dev and cloud AGREE. It would keep passing if every leg
regressed to the single-file bind together. This file asserts the shape is
CORRECT, not merely uniform.

Venue: :7999 — parses a YAML file, touches no server and no shared state.
"""

import os

import pytest
import yaml

PROJECT_ROOT = os.environ.get( "LUPIN_ROOT" )
if PROJECT_ROOT is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )

COMPOSE_FILE = "docker-compose.yml"
CLAUDE_HOME  = "/home/rruiz/.claude"
SESSIONS_DIR = "/home/rruiz/.claude/sessions"

# service name -> the named volume it must mount at CLAUDE_HOME
SERVICES = {
    "lupin-rest-dev" : "claude-creds-dev",
    "lupin-rest-test": "claude-creds-test",
}


@pytest.fixture( scope="module" )
def compose():
    with open( os.path.join( PROJECT_ROOT, COMPOSE_FILE ) ) as fh:
        return yaml.safe_load( fh )


def _entries( compose, service ):
    """Volume entries for one service, normalized to ( source, target ) pairs."""
    out = []
    for v in compose[ "services" ][ service ].get( "volumes" ) or []:
        if isinstance( v, dict ):
            out.append( ( v.get( "source" ), v.get( "target" ) ) )
        else:
            parts = str( v ).split( ":" )
            out.append( ( parts[ 0 ], parts[ 1 ] if len( parts ) >= 2 else None ) )
    return out


@pytest.mark.parametrize( "service,volume_name", sorted( SERVICES.items() ) )
def test_claude_home_is_a_named_volume( compose, service, volume_name ):
    """The container's .claude must be its own named volume, not a host bind."""
    sources = [ src for src, tgt in _entries( compose, service ) if tgt == CLAUDE_HOME ]
    assert sources == [ volume_name ], (
        f"{service} must mount the named volume {volume_name!r} at {CLAUDE_HOME}; "
        f"found {sources!r}. A host bind here cannot follow the ~3x/day token "
        f"replacement (row c7c60896)."
    )


@pytest.mark.parametrize( "service", sorted( SERVICES ) )
def test_the_single_file_credential_bind_is_gone( compose, service ):
    """
    The exact regression: re-binding the credential FILE from the host.

    Asserted separately from the volume check because both could be present at
    once — a more-specific file bind nested under the volume would re-introduce
    the stale-inode failure while the volume assertion above still passed.
    """
    offenders = [
        ( src, tgt ) for src, tgt in _entries( compose, service )
        if tgt and tgt.endswith( ".credentials.json" )
    ]
    assert not offenders, (
        f"{service} binds the credential file directly: {offenders!r}. Docker resolves "
        f"a single-file bind by inode at container start; Claude Code renews by "
        f"REPLACING the file, so the container strands on a dead token. Dropping :ro "
        f"does NOT fix it (rename fails 'Resource busy'), and a host symlink does not "
        f"either (rename replaces the link, not its target). Both measured 2026-08-01/02."
    )


@pytest.mark.parametrize( "service", sorted( SERVICES ) )
def test_sessions_bind_is_declared_after_the_volume( compose, service ):
    """
    Ordering is load-bearing, not cosmetic.

    The claude-creds volume mounts over the WHOLE .claude directory and shadows
    `sessions/`. The nested bind wins only because compose applies it afterwards.
    Get the order wrong and request_persona() 404s — which is exactly what happened
    to the VM on 2026-07-24 (fixed in b7ea000f).
    """
    targets = [ tgt for _, tgt in _entries( compose, service ) ]
    assert CLAUDE_HOME in targets,  f"{service} is missing the {CLAUDE_HOME} mount"
    assert SESSIONS_DIR in targets, (
        f"{service} is missing the {SESSIONS_DIR} bind — the claude-creds volume "
        f"would shadow it with an empty dir and persona lookup would 404."
    )
    assert targets.index( CLAUDE_HOME ) < targets.index( SESSIONS_DIR ), (
        f"{service} declares {SESSIONS_DIR} BEFORE {CLAUDE_HOME}. The volume would "
        f"then shadow the sessions bind (VM persona-404, 2026-07-24)."
    )


def test_the_two_services_do_not_share_one_credential_volume( compose ):
    """
    Separate grants on purpose.

    One shared volume would mean two containers renewing a single credential —
    re-creating the two-writers race this change exists to remove, just between
    dev and test instead of host and container.
    """
    assert SERVICES[ "lupin-rest-dev" ] != SERVICES[ "lupin-rest-test" ], (
        "dev and test must hold separate credential volumes"
    )
    dev  = [ src for src, tgt in _entries( compose, "lupin-rest-dev" )  if tgt == CLAUDE_HOME ]
    test = [ src for src, tgt in _entries( compose, "lupin-rest-test" ) if tgt == CLAUDE_HOME ]
    assert dev != test, f"dev and test share credential volume {dev!r} — two writers, one token"


@pytest.mark.parametrize( "volume_name", sorted( SERVICES.values() ) )
def test_credential_volumes_are_declared( compose, volume_name ):
    """A volume referenced but not declared makes compose fail at up-time, not here."""
    declared = compose.get( "volumes" ) or {}
    assert volume_name in declared, (
        f"{volume_name} is mounted by a service but absent from the top-level "
        f"`volumes:` block"
    )


def test_the_regression_would_actually_be_caught():
    """
    Control — prove these assertions can FAIL.

    A shape test that only ever passes by finding nothing wrong is indistinguishable
    from one that checks nothing (standing Lupin rule). Feed the helpers the OLD,
    broken compose shape and require every guard to reject it.
    """
    broken = {
        "services": {
            "lupin-rest-dev": {
                "volumes": [
                    "~/.claude/sessions:/home/rruiz/.claude/sessions",
                    "~/.claude/.credentials.json:/home/rruiz/.claude/.credentials.json:ro",
                ]
            }
        },
        "volumes": {},
    }

    entries = _entries( broken, "lupin-rest-dev" )
    targets = [ tgt for _, tgt in entries ]

    # 1. no named volume at .claude
    assert [ src for src, tgt in entries if tgt == CLAUDE_HOME ] == [], \
        "control is wrong: the broken shape should have no .claude volume"
    # 2. the single-file bind is present and would be flagged
    assert [ ( s, t ) for s, t in entries if t and t.endswith( ".credentials.json" ) ], \
        "control is wrong: the broken shape must contain the credential file bind"
    # 3. ordering guard has nothing to anchor on
    assert CLAUDE_HOME not in targets, \
        "control is wrong: the broken shape should not mount .claude at all"
    # 4. volume declaration guard would fail
    assert "claude-creds-dev" not in ( broken.get( "volumes" ) or {} ), \
        "control is wrong: the broken shape declares no credential volume"
