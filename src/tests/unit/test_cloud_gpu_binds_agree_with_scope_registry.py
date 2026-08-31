"""
Every enumerated bind in the VM compose file must name a scope the INI actually
serves, at the SAME container path.

WHY THIS TEST EXISTS. On 2026-08-31 the cloud-gpu FastAPI container would not
start. The doc-viewer registry is fail-SOFT about a missing repo — it warns and
skips (`_scope_registry.py`) — so the registry was never going to be the thing
that killed startup. The bind mounts are fail-HARD: `docker-compose.cloud-gpu.yml`
enumerates its host paths long-form with `create_host_path: false`, deliberately,
so a missing host directory stops the container rather than silently auto-creating
an empty one that registers a scope and serves 404s.

⇒ TWO LAYERS WITH OPPOSITE FAILURE MODES, AND NOTHING COMPARED THEM. A bind can
name a container path the INI does not serve (mounted for nobody), or the INI can
point at a container path nothing mounts (a scope that resolves to nothing on that
box). Both read as correct in their own file.

WHAT THIS TEST CANNOT DO, stated so its green is not over-read: it compares two
files in this repo. It says NOTHING about whether the host directories exist on
the VM — that is the fail-hard condition and it is only observable from the box.
A green here means the two declarations agree, not that the container will start.
"""
import re
from pathlib import Path

import pytest
import yaml

import cosa.utils.util as cu


COMPOSE_REL = "/docker-compose.cloud-gpu.yml"
INI_REL     = "/src/conf/lupin-app.ini"
CTR_PREFIX  = "/var/external-projects/"


def _compose_external_binds():
    """
    Container paths bound under /var/external-projects by the VM compose file.

    Ensures:
        - returns {container_target: host_source} for every external-projects bind
        - reads the shipped compose file, never a restatement of it
    """
    doc = yaml.safe_load( Path( cu.get_project_root() + COMPOSE_REL ).read_text() )

    binds = {}
    for service in doc.get( "services", {} ).values():
        for volume in service.get( "volumes", [] ):
            # Long form only — the short "host:ctr:ro" string form is not used for
            # these, and the long form is what carries create_host_path: false.
            if isinstance( volume, dict ) and str( volume.get( "target", "" ) ).startswith( CTR_PREFIX ):
                binds[ volume[ "target" ] ] = volume.get( "source" )

    return binds


def _ini_scope_paths():
    """
    name → container path for every repo named in the INI's `external repos` list.

    Ensures:
        - returns only names that are BOTH listed and given a path
        - parses the shipped INI text rather than importing the app
    """
    text  = Path( cu.get_project_root() + INI_REL ).read_text()

    listed = re.search( r"^external repos\s*=\s*(.+)$", text, re.M )
    if listed is None:
        pytest.fail( f"no `external repos` list found in {INI_REL} — has the key been renamed?" )
    names = [ n.strip() for n in listed.group( 1 ).split( "," ) if n.strip() ]

    paths = {}
    for name in names:
        hit = re.search(
            rf"^external repo {re.escape( name )} path\s*=\s*(\S+)\s*$", text, re.M
        )
        if hit is not None:
            paths[ name ] = hit.group( 1 )

    return paths


def test_every_vm_bind_names_a_scope_the_ini_serves():
    """
    A bind with no matching INI scope mounts a directory nothing will ever read —
    and, worse, it is a fail-HARD dependency on a host path taken on for no reason.
    """
    binds       = _compose_external_binds()
    ini_targets = set( _ini_scope_paths().values() )

    assert binds, (
        f"parsed ZERO external-projects binds out of {COMPOSE_REL}. This test cannot "
        f"fail meaningfully if it finds nothing — the volume format has changed and "
        f"the parser needs re-pointing, not the assertion relaxing."
    )

    orphans = sorted( target for target in binds if target not in ini_targets )

    assert orphans == [], (
        f"{len( orphans )} bind target(s) in {COMPOSE_REL} match no `external repo <name> path` "
        f"in {INI_REL}: {orphans}. Each is a hard start-time dependency on a host directory "
        f"whose contents nothing serves."
    )


def test_a_scope_and_its_bind_agree_on_the_container_path():
    """
    The silent half: bind and INI both present, pointing at different container
    paths. Nothing errors — the scope simply resolves to an unmounted path.
    """
    binds     = _compose_external_binds()
    ini_paths = _ini_scope_paths()

    # Match on the LAST path segment, which is the only thing the two files share.
    by_leaf   = { Path( target ).name: target for target in binds }
    mismatched = [
        f"{name}: ini={path} bind={by_leaf[ Path( path ).name ]}"
        for name, path in ini_paths.items()
        if Path( path ).name in by_leaf and by_leaf[ Path( path ).name ] != path
    ]

    assert mismatched == [], (
        f"scope path and bind target disagree for: {mismatched}. The scope will register "
        f"and resolve to a path nothing is mounted at."
    )


def test_the_parser_can_actually_see_a_planted_disagreement():
    """
    Positive control. An empty parse and a clean tree produce the same green, so
    prove the comparison would catch a real mismatch before trusting its silence.
    """
    binds = _compose_external_binds()
    assert binds, "nothing parsed — see the message on the orphan test"

    ini_targets = set( _ini_scope_paths().values() )
    planted     = CTR_PREFIX + "google/a-repo-that-is-not-registered"

    assert planted not in ini_targets, "planted control path is somehow registered; pick another"

    orphans = sorted( t for t in { **binds, planted: "/host/nowhere" } if t not in ini_targets )
    assert planted in orphans, (
        "the orphan comparison did not flag a path that is provably absent from the INI — "
        "it is not discriminating, and its green above means nothing."
    )
