"""
Every external doc-viewer scope the INI declares must have a bind-mount behind it — or be
recorded, by name and with a reason, as deliberately absent on that deployment.

WHAT THIS CATCHES, and it is a real 2026-07-25 outage on the GCP test VM:

    [scope_registry] WARNING: external repo 'lupin': path '/var/external-projects/lupin' not
                              found on disk; skipping
    ... x12 ...
    [scope_registry] registered 0 external scope(s): []
    GET /api/io/file?path=skills-distillation/... -> 404

`docker-compose.cloud-gpu.yml` was written from the code-mount set only. The two doc-viewer
binds `docker-compose.yml` has carried since 2026-05-12 were never copied across, so on the VM
NOTHING resolved. The container paths are fixed by `lupin-app.ini § external repos`; the compose
file is the only place they can be satisfied. Nothing compared the two — so this does.

THE ASYMMETRY THIS TEST IS SHAPED AROUND. A missing mount is not equally bad in both
directions, and the fix must not trade the loud failure for the quiet one:

  path ABSENT   -> registry logs a WARNING per repo and skips it. LOUD. This is what surfaced
                   the outage, and it is the behaviour to protect.
  path PRESENT
  but EMPTY     -> registry registers the scope and every file under it 404s. SILENT. No
                   warning is possible, because from the registry's side the path exists.

Which is why the compose files bind these LONG-FORM with `create_host_path: false`, and why
`test_long_form_binds_declare_create_host_path` below is not style policing: a short-syntax
bind auto-creates the missing host directory and converts the loud failure into the quiet one.
Measured 2026-07-25 on both machines, because they disagree — dev compose v2.19.1 does not
auto-create a long-form bind, VM compose v5.3.1 DOES, and only the key stops it there.

WHAT THIS TEST CANNOT SEE:
  1. It is STATIC. A compose file can declare a perfect mount set against a host path that does
     not exist; only `src/tests/smoke/test_container_preflight.py` (host, docker required) sees
     the running container. This tier answers "was it ever written down", not "is it mounted".
  2. It does not verify the host SOURCE paths, which differ per machine by design.
  3. KNOWN_ABSENT is a policy statement in this file, not in the compose file. It is checked in
     BOTH directions — an entry that is actually covered fails too — so it cannot rot silently
     into a permanent exemption the way a one-way allow-list does.
"""

import re

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path( __file__ ).resolve().parents[ 4 ]
INI_PATH  = REPO_ROOT / "src" / "conf" / "lupin-app.ini"

# The compose files that stand up a doc-viewer-serving `lupin-rest*` service, and the service
# keys within them. docker-compose.cloud-test.yml is deliberately NOT here: see the module
# docstring's scope note — it is covered when someone adds it, and its absence is visible.
COMPOSE_TARGETS = {
    "docker-compose.yml"           : [ "lupin-rest-dev", "lupin-rest-test" ],
    "docker-compose.cloud-gpu.yml" : [ "lupin-rest" ],
}

# Scopes with no MOUNT on that deployment. The REASON is required, and the test fails if an
# entry here turns out to be covered after all — so landing a mount forces the entry out.
#
# ⚠️ MOUNT-ABSENT, NOT CONTENT-ABSENT — the distinction cost a red here and is worth keeping.
# `lupin-mobile` USED to be exempt from this list on every deployment: its old INI path
# `/var/lupin/src/lupin-mobile` sat inside the `./src -> /var/lupin/src` code mount, so it was
# covered by this test's definition everywhere the code mount existed. On 2026-08-30 Rick moved
# that repo OUT of `src/` to a sibling of lupin, and the INI now points at
# `/var/external-projects/lupin-mobile` (row f2f7b0cd). On dev/test that is still covered — the
# whole projects directory is bound at `/var/external-projects`. On cloud-gpu it is NOT, so the
# scope now needs the entry below. The CONTENT gap named above is unchanged and is the reason
# the honest fix is a KNOWN_ABSENT entry rather than a new mount: the repo is not on the VM.
KNOWN_ABSENT = {
    "docker-compose.cloud-gpu.yml": {
        "cosa-voice"                 : "not cloned on the GCP test VM",
        "claude-plans"               : "~/.claude/plans does not exist on the VM",
        "lookml"                     : "not cloned on the GCP test VM",
        "par-pacific"                : "not cloned on the GCP test VM",
        "retail-ai-location-strategy": "not cloned on the GCP test VM",
        "google-project-wonderwall"  : "not cloned on the GCP test VM",
        "scratchpad"                 : "dev-host scratch project; intentionally not on the VM",
        "skills-distillation"        : "MEASURED ABSENT on the VM 2026-08-31 over IAP — /mnt/lupin-data/google/skills-distillation does not exist there. Its bind was the one stopping the container from starting, and it has been removed. This is the honest state: the repo is not on that box. Restore the bind and drop this entry together if it is ever cloned there.",
        "lupin-mobile"               : "not cloned on the GCP test VM. Until 2026-08-30 it rode the `./src -> /var/lupin/src` code mount as a nested repo and so was never listed here; Rick moved it to a sibling of lupin that day (row f2f7b0cd) and the INI now points at /var/external-projects/lupin-mobile, which cloud-gpu does not bind. Landing a mount for it forces this entry out, which is correct — but the repo has to reach the VM first.",
    },
}


def _declared_scopes():
    """
    Read every `external repo <name> path` key out of the INI.

    Parsed with a regex rather than configparser because the INI's keys contain spaces and the
    file carries duplicate section blocks per environment; this only needs the name->path pairs
    and reading them literally is both cheaper and harder to get subtly wrong.

    Ensures:
        - returns {scope_name: container_path}, both stripped
        - raises if the INI declares no external repos at all — an empty result here would make
          every assertion below vacuously pass, which is the failure mode this suite exists for
    """
    text  = INI_PATH.read_text( encoding="utf-8" )
    pairs = re.findall( r"^external repo (\S+) path\s*=\s*(\S+)\s*$", text, re.MULTILINE )
    scopes = { name: path for name, path in pairs }
    assert scopes, f"no `external repo <name> path` keys found in {INI_PATH} — instrument failure"
    return scopes


def _mount_targets( compose_name, service ):
    """
    Every container-side mount target declared for one service.

    Ensures:
        - returns a list of target paths, short and long syntax alike
        - a named volume (no leading `/` on the source) still yields its target
    """
    doc      = yaml.safe_load( ( REPO_ROOT / compose_name ).read_text( encoding="utf-8" ) )
    volumes  = doc[ "services" ][ service ].get( "volumes" ) or []
    targets  = []
    for vol in volumes:
        if isinstance( vol, dict ):
            targets.append( vol[ "target" ] )
        else:
            # short syntax: <source>:<target>[:<mode>]
            parts = vol.split( ":" )
            if len( parts ) >= 2: targets.append( parts[ 1 ] )
    return targets


def _is_covered( scope_path, targets ):
    """
    Is `scope_path` served by some mount — either bound directly, or living under a bound parent?

    The dev compose binds ONE directory (`/var/external-projects`) that covers every child, so
    a parent match must count. `PurePath.is_relative_to` semantics, spelled out on strings to
    keep the comparison exactly the one the container will make.
    """
    scope_path = scope_path.rstrip( "/" )
    for target in targets:
        target = target.rstrip( "/" )
        if scope_path == target or scope_path.startswith( target + "/" ): return True
    return False


@pytest.mark.parametrize( "compose_name,services", sorted( COMPOSE_TARGETS.items() ) )
def test_every_declared_scope_is_mounted_or_recorded_absent( compose_name, services ):
    """
    Ensures:
        - every INI-declared external scope is either covered by a mount in this compose file,
          or named in KNOWN_ABSENT for it with a non-empty reason
    """
    scopes  = _declared_scopes()
    absent  = KNOWN_ABSENT.get( compose_name, {} )

    for service in services:
        targets = _mount_targets( compose_name, service )
        missing = [ name for name, path in sorted( scopes.items() )
                    if not _is_covered( path, targets ) and name not in absent ]
        assert not missing, (
            f"{compose_name} § {service}: {len( missing )} external scope(s) declared in "
            f"lupin-app.ini have NO bind-mount and are NOT recorded as known-absent: "
            f"{missing}\n"
            f"This is the 2026-07-25 GCP-VM outage shape — the registry logs a WARNING per "
            f"repo, registers 0 scopes, and every /api/io/file request 404s.\n"
            f"FIX: add the bind (long form, with `create_host_path: false`), or add the scope "
            f"to KNOWN_ABSENT['{compose_name}'] with the reason it does not exist there."
        )


@pytest.mark.parametrize( "compose_name,services", sorted( COMPOSE_TARGETS.items() ) )
def test_known_absent_entries_are_not_actually_covered( compose_name, services ):
    """
    THE REVERSE DIRECTION — without it, KNOWN_ABSENT is a one-way ratchet that only ever grows.

    Ensures:
        - no scope named in KNOWN_ABSENT is in fact served by a mount in that compose file
        - every KNOWN_ABSENT entry names a scope the INI actually declares (a typo'd or retired
          scope name would otherwise sit here forever, silently exempting nothing)
        - every reason is non-empty
    """
    scopes = _declared_scopes()
    absent = KNOWN_ABSENT.get( compose_name, {} )

    unknown = sorted( set( absent ) - set( scopes ) )
    assert not unknown, (
        f"KNOWN_ABSENT['{compose_name}'] names scope(s) the INI does not declare: {unknown}. "
        f"Either the scope was renamed/retired (delete the entry) or the name is a typo — "
        f"as written it exempts nothing and hides that fact."
    )

    for name, reason in sorted( absent.items() ):
        assert reason.strip(), f"KNOWN_ABSENT['{compose_name}']['{name}'] has an empty reason"

    for service in services:
        targets = _mount_targets( compose_name, service )
        stale   = [ name for name in sorted( absent )
                    if _is_covered( scopes[ name ], targets ) ]
        assert not stale, (
            f"{compose_name} § {service}: {stale} are recorded in KNOWN_ABSENT but ARE mounted. "
            f"Delete those entries — a stale exemption is how a real gap gets waved through later."
        )


@pytest.mark.parametrize( "compose_name,services", sorted( COMPOSE_TARGETS.items() ) )
def test_long_form_binds_declare_create_host_path( compose_name, services ):
    """
    A long-syntax bind must say `create_host_path: false`.

    NOT STYLE POLICING. Measured 2026-07-25 with a negative control on both machines:

                                       dev (compose v2.19.1)   VM (compose v5.3.1)
      long, no create_host_path         not created             HOST DIR CREATED
      long + create_host_path: false    not created             not created

    On the VM the key is the only thing preventing an auto-created empty directory — which
    converts the registry's LOUD per-repo warning into a scope that registers and 404s in
    silence. A probe run on dev alone concludes the key is redundant, and that conclusion is
    false for the machine these files deploy to.

    Ensures:
        - every long-syntax bind in a doc-viewer-serving service sets bind.create_host_path
          to False
    """
    doc = yaml.safe_load( ( REPO_ROOT / compose_name ).read_text( encoding="utf-8" ) )

    for service in services:
        for vol in doc[ "services" ][ service ].get( "volumes" ) or []:
            if not isinstance( vol, dict ):       continue
            if vol.get( "type" ) != "bind":       continue
            setting = ( vol.get( "bind" ) or {} ).get( "create_host_path" )
            assert setting is False, (
                f"{compose_name} § {service}: long-form bind to '{vol[ 'target' ]}' does not set "
                f"`bind.create_host_path: false` (got {setting!r}). On the VM's compose v5.3.1 a "
                f"long-form bind AUTO-CREATES the missing host dir, turning a loud absence into "
                f"a scope that registers and serves 404s silently."
            )
