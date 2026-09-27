"""
Unit tests for row b84bbf1c — the external-repo doc-viewer binds must stay WRITABLE.

THE DEFECT THIS GUARDS, and it is a two-sided one
    On 2026-09-24 ticket 416d4b00 added `POST /api/docs/upload`. The external-repo binds
    stayed read-only — `:ro` on dev/test, `read_only: true` on the VM — so every upload into
    an external scope got EROFS and the route answered 403. Rick hit it on
    `lupin-rest-cloud-gpu`; his probe measured errno 30 at mkstemp in
    `weil-nda-drafting-suite/src/rnd`. Rick's ruling 02f3bc8f / 6408fd1c flipped them.

    ⚠️ AND THE FLIP WAS UNGUARDED — Rachel measured that reverting it left the suite GREEN.
    A configuration change nothing asserts is a configuration change that comes back: the
    mount and the writer had already disagreed for two days precisely because no test held
    them to each other.

WHY A COMMENT WAS NOT ENOUGH
    The dev binds carried "Read-only by design (viewer never writes)" for two days after the
    writer landed. A stale reassurance is worse than silence — it disarms the reader who
    would otherwise have checked. So the rule lives here, where it fails, and the comment is
    only a courtesy.

⚠️ `~/.claude/plans` IS DELIBERATELY EXCLUDED and stays `:ro`. It is NOT an upload scope:
    the doc viewer serves plans read-only and nothing writes to that mount. Making it
    writable would widen the blast radius for no feature, so this file asserts it stays
    read-only rather than ignoring it — an exclusion nothing checks is indistinguishable
    from an oversight.

Venue: :7999 / AI-discretionary. Pure file reads, milliseconds.
"""
import os

import pytest
import yaml

import cosa.utils.util as cu

PROJECT_ROOT   = cu.get_project_root()
DEV_COMPOSE    = os.path.join( PROJECT_ROOT, "docker-compose.yml" )
VM_COMPOSE     = os.path.join( PROJECT_ROOT, "docker-compose.cloud-gpu.yml" )

# The container-side prefix every external repo scope is served from.
EXTERNAL_PREFIX = "/var/external-projects"

# Deliberately read-only, and asserted so rather than skipped. See the module docstring.
READ_ONLY_BY_DESIGN = "/var/external-claude/plans"

# Dev binds the projects PARENT once per service; the VM enumerates children.
SERVICES_WITH_EXTERNAL_MOUNTS = [ "lupin-rest-dev", "lupin-rest-test" ]


def _compose( path ):
    with open( path ) as f:
        return yaml.safe_load( f )


def _short_form_binds( service ):
    """The `host:container[:opts]` string volumes, as (target, opts) pairs."""
    out = [ ]
    for vol in service.get( "volumes", [ ] ):
        if not isinstance( vol, str ):
            continue
        parts = vol.split( ":" )
        if len( parts ) >= 2:
            out.append( ( parts[ 1 ], parts[ 2 ] if len( parts ) > 2 else "" ) )
    return out


def _long_form_binds( service ):
    """The mapping-style volumes, as (target, read_only) pairs."""
    return [
        ( vol.get( "target", "" ), bool( vol.get( "read_only", False ) ) )
        for vol in service.get( "volumes", [ ] )
        if isinstance( vol, dict )
    ]


@pytest.mark.parametrize( "service", SERVICES_WITH_EXTERNAL_MOUNTS )
def test_dev_external_project_binds_are_writable( service ):
    """
    `:ro` on the dev/test `/var/external-projects` bind is what made the upload 403.

    Reddens by name if anybody puts the suffix back.
    """
    svc      = _compose( DEV_COMPOSE )[ "services" ][ service ]
    binds    = _short_form_binds( svc )
    external = [ ( t, o ) for t, o in binds if t == EXTERNAL_PREFIX ]

    assert external, (
        f"{service} does not bind {EXTERNAL_PREFIX} at all — the doc viewer's external "
        f"scopes cannot resolve, and this guard would otherwise pass by finding nothing" )

    read_only = [ t for t, o in external if "ro" in o.split( "," ) ]
    assert not read_only, (
        f"{service} mounts {read_only} READ-ONLY. POST /api/docs/upload writes into external "
        f"scopes, so `:ro` here returns EROFS and the route answers 403 (row b84bbf1c, "
        f"Rick's ruling 02f3bc8f). Drop the `:ro` suffix." )


def test_the_vm_external_repo_binds_are_writable():
    """
    The VM enumerates one bind per external repo, long-form, with `read_only:`.

    Reddens by name if any of them goes back to `read_only: true`.
    """
    services = _compose( VM_COMPOSE )[ "services" ]
    offenders = [ ]
    found     = 0
    for name, svc in services.items():
        for target, read_only in _long_form_binds( svc ):
            if target.startswith( EXTERNAL_PREFIX ):
                found += 1
                if read_only:
                    offenders.append( f"{name}:{target}" )

    assert found, (
        f"no bind under {EXTERNAL_PREFIX} found in docker-compose.cloud-gpu.yml — a guard "
        f"that finds nothing passes for the wrong reason, so this fails instead" )
    assert not offenders, (
        f"these VM external-repo binds are read_only: {offenders}. Rick's probe measured "
        f"errno 30 (EROFS) at mkstemp in weil-nda-drafting-suite/src/rnd with these "
        f"read-only; uploads into external scopes 403 (row b84bbf1c)." )


def test_the_vm_external_binds_keep_create_host_path_false():
    """
    Flipping `read_only` must not disturb `create_host_path: false`, which is load-bearing
    ON THE VM specifically: without it compose AUTO-CREATES a missing host dir, the scope
    registry then FINDS the path, registers the scope, and serves 404s for every file in it
    with no warning. Loud absence beats a scope resolving to nothing.
    """
    services = _compose( VM_COMPOSE )[ "services" ]
    missing  = [ ]
    for name, svc in services.items():
        for vol in svc.get( "volumes", [ ] ):
            if not isinstance( vol, dict ):
                continue
            if vol.get( "target", "" ).startswith( EXTERNAL_PREFIX ):
                if vol.get( "bind", { } ).get( "create_host_path" ) is not False:
                    missing.append( f"{name}:{vol.get( 'target' )}" )

    assert not missing, (
        f"these external binds lost `create_host_path: false`: {missing}. On the VM that key "
        f"is what stops compose auto-creating a missing host dir, which would register a "
        f"scope that serves 404s for everything in it — silently." )


@pytest.mark.parametrize( "service", SERVICES_WITH_EXTERNAL_MOUNTS )
def test_the_plans_mount_stays_read_only( service ):
    """
    ⚠️ AN EXCLUSION NOTHING CHECKS IS INDISTINGUISHABLE FROM AN OVERSIGHT.

    `~/.claude/plans` is NOT an upload scope — the viewer serves it read-only and nothing
    writes there — so it was deliberately left `:ro` when the external-project binds were
    flipped. This asserts that deliberateness, so a later sweep cannot widen it by analogy.
    """
    svc   = _compose( DEV_COMPOSE )[ "services" ][ service ]
    plans = [ ( t, o ) for t, o in _short_form_binds( svc ) if t == READ_ONLY_BY_DESIGN ]

    assert plans, f"{service} no longer binds {READ_ONLY_BY_DESIGN} — this guard found nothing"
    for target, opts in plans:
        assert "ro" in opts.split( "," ), (
            f"{service} mounts {target} WRITABLE. It is not an upload scope; nothing writes "
            f"there, so writability is blast radius bought for no feature (row b84bbf1c)." )
