"""
install_db_secrets.py under real sudo and real visudo, in a container made for the test.

The installer is run for real, through docker exec, as an ordinary account in a throwaway container.
Venue: host-side, docker and network required (it installs the sudo package in the container, about 3 s).
It never runs sudo on this host. The merge gate's containers have no docker socket, so there every test skips.
The container is removed afterwards, and a start-of-run sweep removes old leftovers.
"""

# Layers keeping the test away from anything real:
#   1. the container gets no host mount: the two scripts are copied in with `docker cp`
#   2. a name guard: the prefix and the label must both match, and the real containers are refused
#   3. every command is `docker exec` on the generated container name alone

import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

import cosa.utils.util as cu

IMAGE           = "ghcr.io/astral-sh/uv:python3.13-bookworm-slim"
NAME_PREFIX     = "lupin-dbsecrets-test-"
LABEL           = "lupin.test=install-db-secrets"
REAL_CONTAINERS = ( "lupin-postgres", "lupin-rest-dev", "lupin-rest-test", "lupin-model-server" )
RUN_LABEL_KEY   = "lupin.test.run"
RUN_ID          = uuid.uuid4().hex[ :12 ]
SWEEP_MIN_AGE   = timedelta( minutes=30 )
SCRIPTS         = os.path.join( cu.get_project_root(), "src/scripts" )
SAMPLE_TEXT        = "container-test-password"
APP_FILE        = "/etc/lupin/secrets/db_app_password"
TEST_FILE       = "/etc/lupin/secrets/db_test_password"
COPY            = "/usr/local/sbin/lupin-install-db-secrets"
SUDOERS         = "/etc/sudoers.d/lupin-install-db-secrets"
INSTALLER       = "/opt/repo/src/scripts/install_db_secrets.py"


# ── guards, tested without docker ───────────────────────────────────────────

def refuse_unless_throwaway( name, labels ):
    """
    Refuse any container that is not one this test made.

    Requires:
        - name is a container name; labels is a list of "key=value" strings

    Ensures:
        - returns None only when the name has the throwaway prefix, is not a real container, and the label is present
        - raises RuntimeError for anything else
    """
    if name in REAL_CONTAINERS: raise RuntimeError( f"SAFETY: {name} is a real container" )
    if not name.startswith( NAME_PREFIX ): raise RuntimeError( f"SAFETY: {name!r} does not start with {NAME_PREFIX!r}" )
    if LABEL not in labels: raise RuntimeError( f"SAFETY: {name!r} does not carry the label {LABEL!r}" )


def sweepable( name, labels, created, now ):
    """Whether the sweep may remove this container.

    It must pass the guard, not belong to this run, and be old enough for a peer's live one to survive.
    """
    try:
        refuse_unless_throwaway( name, labels )
    except RuntimeError:
        return False
    if f"{RUN_LABEL_KEY}={RUN_ID}" in labels: return False
    return now - created >= SWEEP_MIN_AGE


@pytest.mark.parametrize( "name, labels, ok", [
    ( NAME_PREFIX + "abc", [ LABEL ],       True ),
    ( NAME_PREFIX + "abc", [ ],             False ),
    ( "lupin-postgres",    [ LABEL ],       False ),
    ( "lupin-rest-test",   [ LABEL ],       False ),
    ( "x" + NAME_PREFIX,   [ LABEL ],       False ),
] )
def test_the_guard_needs_both_the_prefix_and_the_label( name, labels, ok ):
    if ok:
        assert refuse_unless_throwaway( name, labels ) is None
    else:
        with pytest.raises( RuntimeError ): refuse_unless_throwaway( name, labels )


NOW = datetime( 2026, 1, 1, 12, 0, tzinfo=timezone.utc )


@pytest.mark.parametrize( "labels, age_minutes, expected", [
    ( [ LABEL ],                                      31, True ),
    ( [ LABEL ],                                      29, False ),
    ( [ LABEL, f"{RUN_LABEL_KEY}={RUN_ID}" ],        600, False ),
    ( [ ],                                           600, False ),
] )
def test_the_sweep_spares_young_unlabelled_and_own_containers( labels, age_minutes, expected ):
    assert sweepable( NAME_PREFIX + "x", labels, NOW - timedelta( minutes=age_minutes ), NOW ) is expected


# ── the container ───────────────────────────────────────────────────────────

def _docker( *args, check=True, timeout=180 ):
    """Run a docker command and return the CompletedProcess."""
    return subprocess.run( [ "docker", *args ], capture_output=True, text=True, timeout=timeout, check=check )


def _docker_ready():
    """Say why docker or the image is not usable, or None when both are."""
    if shutil.which( "docker" ) is None: return "docker CLI not available"
    if _docker( "info", check=False, timeout=30 ).returncode != 0: return "docker daemon not reachable"
    if _docker( "image", "inspect", IMAGE, check=False ).returncode != 0: return f"image {IMAGE} not present locally"
    return None


def _sweep_leftovers():
    """Remove old throwaway containers of this test, never one of this run and never a young one."""
    listing = _docker( "ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.Names}}|{{.Labels}}|{{.CreatedAt}}", check=False ).stdout
    for row in listing.splitlines():
        name, labels, created = row.split( "|", 2 )
        stamp = datetime.strptime( created[ :19 ], "%Y-%m-%d %H:%M:%S" ).replace( tzinfo=timezone.utc )
        if sweepable( name, labels.split( "," ), stamp, datetime.now( timezone.utc ) ): _docker( "rm", "-f", "-v", name, check=False )


class Box:
    """A guarded throwaway container and the commands that run inside it."""
    def __init__( self, name ):
        self.name = name
    def sh( self, script, user="root" ):
        """Run a shell snippet as a user in the container; return ( exit code, output )."""
        done = _docker( "exec", "-u", user, self.name, "sh", "-c", script, check=False )
        return done.returncode, done.stdout + done.stderr
    def stat( self, path ):
        """Return 'owner:group mode' of a path in the container, or None."""
        code, text = self.sh( f"stat -c '%u:%g %a' {path}" )
        return text.strip() if code == 0 else None
    def read( self, path ):
        """Return a file's content as root, or None."""
        code, text = self.sh( f"cat {path}" )
        return text if code == 0 else None


@pytest.fixture( scope="module" )
def box():
    """A fresh container with sudo, an operator account and the repository scripts.

    A bootstrap sudo rule stands in for typing a password on the first run.
    """
    why = _docker_ready()
    if why: pytest.skip( why )
    _sweep_leftovers()
    name = NAME_PREFIX + uuid.uuid4().hex[ :10 ]
    refuse_unless_throwaway( name, [ LABEL ] )
    _docker( "run", "-d", "--name", name, "--label", LABEL, "--label", f"{RUN_LABEL_KEY}={RUN_ID}",
             "--memory", "512m", "--cpus", "1", "--pids-limit", "256", "--entrypoint", "sleep", IMAGE, "900" )
    try:
        made = Box( name )
        code, text = made.sh( "apt-get update -qq >/dev/null 2>&1 && apt-get install -y -qq sudo >/dev/null 2>&1 && which visudo" )
        if code != 0: pytest.skip( f"cannot install sudo in the container (no network?): {text.strip()[ -200: ]}" )
        setup = (
            "ln -s /usr/local/bin/python3 /usr/bin/python3 && useradd -m -u 1001 op && mkdir -p /opt/repo/src/scripts "
            "&& mkdir -p /etc/lupin/secrets && chmod 750 /etc/lupin/secrets && printf 'app-pw\\n' > " + APP_FILE + " "
            "&& mkdir -p /home/op/.lupin && printf '" + SAMPLE_TEXT + "\\n' > /home/op/.lupin/db_test_pw && chmod 600 /home/op/.lupin/db_test_pw "
            "&& chown -R op:op /home/op/.lupin && chown -R op:op /opt/repo"
        )
        assert made.sh( setup )[ 0 ] == 0
        for script in ( "install_db_secrets.py", "lupin_install_db_secrets.py" ):
            _docker( "cp", os.path.join( SCRIPTS, script ), f"{name}:/opt/repo/src/scripts/{script}" )
        assert made.sh( "chown -R op:op /opt/repo && chmod +x " + INSTALLER )[ 0 ] == 0
        # Stands in for typing a password: the first run needs sudo, and the narrow rule does not exist yet.
        assert made.sh( "printf 'op ALL=(root) NOPASSWD: ALL\\n' > /etc/sudoers.d/00-bootstrap && chmod 440 /etc/sudoers.d/00-bootstrap" )[ 0 ] == 0
        yield made
    finally:
        _docker( "rm", "-f", "-v", name, check=False )


def _nothing_installed( box ):
    """Assert none of the three steps left anything behind."""
    assert box.stat( COPY ) is None and box.stat( SUDOERS ) is None and box.stat( TEST_FILE ) is None


# ── scenarios, in order ─────────────────────────────────────────────────────

def test_a_refusal_before_any_change_changes_nothing( box ):
    assert box.sh( "mv /home/op/.lupin/db_test_pw /home/op/.lupin/away" )[ 0 ] == 0
    code, text = box.sh( f"sudo {INSTALLER}", user="op" )
    assert code == 16, text
    assert "did not: copy of the payload, sudoers line, run of the installed copy" in text
    _nothing_installed( box )
    assert box.sh( "mv /home/op/.lupin/away /home/op/.lupin/db_test_pw" )[ 0 ] == 0


def test_check_before_installing_reports_missing_and_changes_nothing( box ):
    code, text = box.sh( f"sudo {INSTALLER} --check", user="op" )
    assert code == 1, text
    assert "copy of the payload: missing" in text and "sudoers line: missing" in text
    _nothing_installed( box )


def test_a_set_that_visudo_refuses_takes_the_new_line_out_again( box ):
    assert box.sh( "printf 'this is not valid sudoers\\n' > /etc/sudoers.d/zz-broken && chmod 440 /etc/sudoers.d/zz-broken" )[ 0 ] == 0
    code, text = box.sh( f"sudo {INSTALLER}", user="op" )
    box.sh( "rm -f /etc/sudoers.d/zz-broken" )
    assert code == 27, text
    assert "done: copy of the payload; did not: sudoers line, run of the installed copy" in text
    assert box.stat( SUDOERS ) is None and box.stat( SUDOERS + ".new" ) is None and box.stat( TEST_FILE ) is None


def test_the_install_makes_the_three_things_with_the_right_owner_and_mode( box ):
    code, text = box.sh( f"sudo {INSTALLER}", user="op" )
    assert code == 0, text
    assert box.stat( COPY ) == "0:0 755"
    assert box.stat( SUDOERS ) == "0:0 440"
    assert box.stat( TEST_FILE ) == "0:1002 440"
    assert box.stat( APP_FILE ) == "0:1002 440"
    assert box.read( TEST_FILE ).strip() == SAMPLE_TEXT
    assert box.read( SUDOERS ) == f'op ALL=(root) NOPASSWD: {COPY} ""\n'
    assert SAMPLE_TEXT not in text
    assert box.sh( "visudo -c" )[ 0 ] == 0


def test_a_second_run_changes_nothing_and_check_is_all_ok( box ):
    code, text = box.sh( f"sudo {INSTALLER}", user="op" )
    assert code == 0, text
    assert text.count( "unchanged" ) >= 3
    code, text = box.sh( f"sudo {INSTALLER} --check", user="op" )
    assert code == 0, text
    assert text.count( ": ok" ) == 3


def test_the_narrow_rule_runs_the_copy_with_no_password_and_no_arguments( box ):
    assert box.sh( "rm /etc/sudoers.d/00-bootstrap" )[ 0 ] == 0
    code, text = box.sh( f"sudo -n {COPY}", user="op" )
    assert code == 0, text
    assert text.count( "unchanged" ) == 2
    code, text = box.sh( f"sudo -n {COPY} --anything", user="op" )
    assert code != 0 and "unchanged" not in text
    code, text = box.sh( f"sudo -n {INSTALLER}", user="op" )
    assert code != 0                    # the rule names one file; the installer is not it
