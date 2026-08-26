"""
Guard for bug 70794d58 — `cloudsql-socket-init` deletes the LIVE socket of an
already-running Cloud SQL proxy.

WHY THIS FILE EXISTS
--------------------
The remedy (`--no-deps` on every service-scoped `compose up`) landed on ONE call
site — `lupin-vm.sh deploy` — and was never swept to its siblings. At the time
this guard was written a repo-wide `grep no.deps src/tests/ src/cosa/tests/`
returned ZERO hits, so the landed fix was protected by nothing at all and could
be dropped by any future edit without a single test going red.

THE MECHANISM, MEASURED (docker compose v2.19.1, isolated throwaway project)
---------------------------------------------------------------------------
Graph, in docker-compose.cloud-gpu.yml (and, until it was retired on 2026-08-26,
identically in docker-compose.cloud-test.yml):

    lupin-rest --depends_on(service_healthy)--> cloud-sql-proxy
    cloud-sql-proxy --depends_on(service_completed_successfully)--> cloudsql-socket-init

`cloudsql-socket-init` runs `rm -f /cloudsql/*/.s.PGSQL.5432`. It exists to clear
a STALE socket after a VM stop/suspend (bug 300bc7ca). But recreating the APP
walks the dependency graph and re-runs it, and when the proxy is ALREADY RUNNING
that `rm` deletes the socket the live proxy owns. The proxy binds once at start
and never re-creates it.

Four arms, all as predicted before running:

    1. up -d                                   -> socket PRESENT, init ran 1x
    2. up -d --force-recreate app              -> socket ABSENT,  init ran 2x   <-- the bug
       ...and the proxy still reported `running health=healthy` throughout,
       because its healthcheck probes :9090 and never touches the socket.
    3. up -d --no-deps --force-recreate app    -> socket PRESENT, init still 2x <-- the fix
    4. up -d --force-recreate <container_name> -> "no such service: ..."

Arm 2 is why this guard must fail when `--no-deps` is removed; arm 4 is why the
second test below exists at all.

WHAT EACH TEST PINS
-------------------
`test_socket_init_graph_premise_holds` pins the PREMISE. Every other test here is
only worth running while that graph is real — if socket-init is ever deleted or
its `rm` dropped, this guard's whole reason evaporates and we should be told that
loudly, rather than have the remaining tests keep passing for a reason that no
longer exists.

`test_every_service_scoped_compose_up_carries_no_deps` is the control that fails
when the fix is removed.

`test_compose_verbs_reference_a_real_service` catches the container-name-for-
service-name class (arm 4). The case that produced this arm: `deploy-cloud-test.sh`
AXIS-B passed `lupin-rest-cloud-test` (a container_name) to `compose pull`/`compose
up`; under `set -e` it aborted on the `pull` and so had NEVER completed. That also
made its missing `--no-deps` LATENT rather than lucky — fixing the service name
alone would have ARMED the socket-deletion bug.

That script and its compose file were RETIRED on 2026-08-26 (row 0d175dac), so the
arm no longer has that subject. It is kept, and still runs against lupin-vm.sh: the
mistake it catches is a shape any deploy script can make, and the reason this file
exists at all is that the original fix was protected by nothing.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path( __file__ ).resolve().parents[ 4 ]

# The deploy scripts that drive `docker compose` against a cloud compose file.
# Each entry: script path -> the compose file whose services it names.
DEPLOY_SCRIPTS = {
    "src/scripts/lupin-vm.sh" : "docker-compose.cloud-gpu.yml",
}

COMPOSE_FILES = [ "docker-compose.cloud-gpu.yml" ]

# `up -d` with NO service argument is a whole-graph bring-up: running socket-init
# is CORRECT there (it is the first-boot path, and `--no-deps` is not even
# meaningful without a named service). Enumerated rather than pattern-matched, so
# a new bare `up -d` appearing somewhere else still has to be justified here.
BARE_UP_EXEMPTIONS = {
    ( "src/scripts/lupin-vm.sh", "svc up" ),
}


def _read( rel ):
    return ( REPO_ROOT / rel ).read_text()


def _script_vars( text ):
    """
    Resolve top-level `NAME="value"` assignments so `$REST_SERVICE` in a compose
    command can be checked against the real compose file. Only simple literal
    assignments — anything computed is left unresolved on purpose, because a
    guard that guesses at a value it cannot see is the failure mode this whole
    file is about.
    """
    out = {}
    for m in re.finditer( r'^([A-Z_][A-Z0-9_]*)="([^"$]*)"', text, re.MULTILINE ):
        out[ m.group( 1 ) ] = m.group( 2 )
    return out


def _compose_up_sites( rel ):
    """
    Every `docker compose ... up -d ...` invocation in a deploy script, in BOTH
    shapes used in this repo:

      (a) direct  : sudo docker compose -f $F --env-file $E up -d --force-recreate $S
      (b) wrapped : remote_compose "up -d --force-recreate $S"

    Shape (b) matters — `remote_compose()` prepends `docker compose -f ...`, so a
    scanner that only understood shape (a) would silently skip every `svc`
    subcommand and report a clean sweep over a file it had barely read.

    Returns list of ( lineno, tail, raw_line ), `tail` being the args after `up -d`.
    """
    sites = []
    for i, line in enumerate( _read( rel ).splitlines(), start=1 ):
        stripped = line.strip()
        if stripped.startswith( "#" ): continue            # comments explain the rule, they do not break it

        m = re.search( r'docker compose\s+.*?\bup\s+-d\b(?P<tail>[^"\n]*)', stripped )
        if m is None:
            m = re.search( r'remote_compose\s+"up\s+-d\b(?P<tail>[^"]*)"', stripped )
        if m is None: continue

        sites.append( ( i, m.group( "tail" ).strip(), stripped ) )
    return sites


def _named_service( tail, variables ):
    """The service argument of a compose `up`, resolved through script vars, or None."""
    for tok in tail.split():
        if tok.startswith( "-" ): continue                  # flags, not the service
        if tok.startswith( "$" ):
            return variables.get( tok.lstrip( "${" ).rstrip( "}" ) )
        return tok
    return None


# ---------------------------------------------------------------------------
# 0. THE PREMISE — every test below is only meaningful while this graph exists.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "compose_rel", COMPOSE_FILES )
def test_socket_init_graph_premise_holds( compose_rel ):
    spec     = yaml.safe_load( _read( compose_rel ) )
    services = spec[ "services" ]

    assert "cloudsql-socket-init" in services, (
        f"{compose_rel}: cloudsql-socket-init is GONE. If that is deliberate, bug 70794d58's "
        f"whole premise is void and this guard file should be deleted with it — do not simply "
        f"delete this assertion and leave the rest passing for a reason that no longer exists."
    )

    init_cmd = " ".join( services[ "cloudsql-socket-init" ][ "command" ] )
    assert ".s.PGSQL.5432" in init_cmd and "rm -f" in init_cmd, (
        f"{compose_rel}: socket-init no longer rm's the socket, so recreating the app can no "
        f"longer delete a live proxy's socket. The --no-deps requirement below may be obsolete "
        f"— re-derive it rather than assuming."
    )

    # proxy waits for the one-shot to COMPLETE — this condition is what makes an
    # app-scoped recreate walk back and re-run the rm.
    assert services[ "cloud-sql-proxy" ][ "depends_on" ][ "cloudsql-socket-init" ][ "condition" ] \
        == "service_completed_successfully", f"{compose_rel}: proxy->socket-init condition changed"

    # ...and the app waits on the proxy, which is what drags socket-init into an
    # `up -d --force-recreate lupin-rest`.
    assert services[ "lupin-rest" ][ "depends_on" ][ "cloud-sql-proxy" ][ "condition" ] \
        == "service_healthy", f"{compose_rel}: lupin-rest->proxy condition changed"


@pytest.mark.parametrize( "compose_rel", COMPOSE_FILES )
def test_proxy_healthcheck_still_cannot_see_the_socket( compose_rel ):
    """
    The second half of 70794d58: throughout the outage the proxy reported
    "Up 35 hours (healthy)" because its probe never touches the unix socket.

    This is NOT asserting the lie is acceptable — it pins that the false-healthy
    is still POSSIBLE, which is precisely why `--no-deps` (prevention) is load-
    bearing and cannot be traded away for "we'd notice". The day this probe does
    assert the socket, this test should fail and be REPLACED, not deleted.
    """
    spec  = yaml.safe_load( _read( compose_rel ) )
    probe = " ".join( spec[ "services" ][ "cloud-sql-proxy" ][ "healthcheck" ][ "test" ] )
    assert ".s.PGSQL.5432" not in probe, (
        f"{compose_rel}: the proxy healthcheck now references the socket. If it genuinely "
        f"asserts the socket exists, the false-healthy half of 70794d58 is FIXED — update this "
        f"test to assert the new guarantee instead of removing it."
    )


# ---------------------------------------------------------------------------
# 1. THE CONTROL — this is what fails when the fix is removed.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "script_rel", sorted( DEPLOY_SCRIPTS ) )
def test_every_service_scoped_compose_up_carries_no_deps( script_rel ):
    variables = _script_vars( _read( script_rel ) )
    offenders = []

    for lineno, tail, raw in _compose_up_sites( script_rel ):
        service = _named_service( tail, variables )
        if service is None: continue                        # bare `up -d` — see the exemption test
        if "--no-deps" in tail: continue
        offenders.append( f"{script_rel}:{lineno}  {raw}" )

    assert not offenders, (
        "Service-scoped `docker compose up` WITHOUT --no-deps. Recreating the app walks the "
        "dependency graph and re-runs cloudsql-socket-init, whose `rm -f "
        "/cloudsql/*/.s.PGSQL.5432` deletes the socket a LIVE proxy owns and never re-creates "
        "(bug 70794d58 — took :7999 down 2026-07-26, and `docker ps` read 'healthy' throughout).\n"
        "  remedy: add --no-deps to each site below\n    " + "\n    ".join( offenders )
    )


def test_bare_compose_up_exemptions_are_enumerated_not_inferred():
    """
    A bare `up -d` (no service) is the legitimate whole-graph bring-up and is
    exempt. Requiring each one to be listed by hand keeps the exemption from
    quietly widening into "any `up` we forgot to scope".
    """
    found = set()
    for script_rel in DEPLOY_SCRIPTS:
        variables = _script_vars( _read( script_rel ) )
        for lineno, tail, raw in _compose_up_sites( script_rel ):
            if _named_service( tail, variables ) is None:
                found.add( ( script_rel, raw ) )

    unlisted = { s for s in found if not any(
        s[ 0 ] == e[ 0 ] and e[ 1 ] in s[ 1 ] or s[ 0 ] == e[ 0 ] for e in BARE_UP_EXEMPTIONS ) }
    assert not unlisted, (
        f"Unenumerated bare `compose up` site(s): {sorted( unlisted )}. A bare up -d re-runs "
        f"socket-init against whatever is already running — justify it in BARE_UP_EXEMPTIONS."
    )


# ---------------------------------------------------------------------------
# 2. THE CLASS THAT MADE THE ABOVE LATENT — container_name where a service goes.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "script_rel", sorted( DEPLOY_SCRIPTS ) )
def test_compose_verbs_reference_a_real_service( script_rel ):
    """
    `docker compose pull|up` resolves SERVICE names. Handed a container_name it
    exits `no such service: <name>` (measured, compose v2.19.1, both verbs).

    The case that produced this arm: deploy-cloud-test.sh AXIS-B passed
    $REST_CONTAINER ("lupin-rest-cloud-test", a container_name) to both verbs, so
    under `set -e` it aborted on the `pull` and had never once completed a
    dependency-axis deploy. That script was retired 2026-08-26 (row 0d175dac); the
    arm still guards every surviving deploy script.
    """
    text        = _read( script_rel )
    variables   = _script_vars( text )
    compose_rel = DEPLOY_SCRIPTS[ script_rel ]
    services    = set( yaml.safe_load( _read( compose_rel ) )[ "services" ] )
    container_names = {
        svc.get( "container_name" )
        for svc in yaml.safe_load( _read( compose_rel ) )[ "services" ].values()
        if svc.get( "container_name" )
    }

    offenders = []
    for i, line in enumerate( text.splitlines(), start=1 ):
        stripped = line.strip()
        if stripped.startswith( "#" ): continue
        m = re.search( r'docker compose\s+.*?\b(?P<verb>up\s+-d|pull)\b(?P<tail>[^"\n]*)', stripped )
        if m is None: continue

        named = _named_service( m.group( "tail" ), variables )
        if named is None: continue
        if named in services: continue
        why = " (that is a container_name, not a service)" if named in container_names else ""
        offenders.append( f"{script_rel}:{i}  resolves to '{named}'{why}\n      {stripped}" )

    assert not offenders, (
        f"`docker compose` handed a name that is not a service in {compose_rel}. compose exits "
        f"'no such service: <name>' and, under `set -e`, the deploy dies there.\n  "
        + "\n  ".join( offenders )
    )
