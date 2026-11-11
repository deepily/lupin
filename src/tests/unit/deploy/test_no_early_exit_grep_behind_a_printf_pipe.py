"""
A `printf | grep -q` under `set -o pipefail` loses an early match.

`grep -q` exits at its first match. The `printf` feeding it then dies of SIGPIPE. Pipefail
reports that death as the pipeline's status, so a successful match reads as no match.
Which process wins is a scheduling race: about 3 runs in 100 under load, never on an idle box.
It showed up as push-env dry-run dying "no row declares LUPIN_CC_VENV" with the row present.
It also showed up as the overlay checks printing a skip line for an overlay that exists.

The fix reads the text through a here-string, which has no pipe.
These tests do not wait for the race. One feeds a list longer than the pipe buffer with the
match on line one. That makes grep leave while printf is still writing, every time.
"""

import os
import re
import subprocess

import cosa.utils.util as cu

ROOT    = cu.get_project_root()
LIB     = f"{ROOT}/src/scripts/lib/preflight-vm-lib.sh"
SCRIPTS = [ "src/scripts/lupin-vm.sh", "src/scripts/preflight-vm.sh", "src/scripts/lib/preflight-vm-lib.sh" ]

# The match is on line one of a list far longer than a 64 KiB pipe buffer. Built inside bash: one
# environment string is capped near 128 KiB, and this list is about 650 KiB.
BIG_SETUP = 'BIG="lupin-rest-test"$\'\\n\'"$( yes yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy | head -n 20000 )"; '

PRINTF_PIPE_GREP_Q = re.compile( r"""printf\s+'%s\\n'\s+"[^"]*"\s*\|\s*grep\s+-[A-Za-z]*q""" )


def _bash( script ):
    return subprocess.run( [ "bash", "-c", script ], env={ **os.environ, "LIB": LIB }, capture_output=True, text=True, timeout=30 )


def test_the_old_shape_really_fails_under_pipefail_with_an_early_match():
    """Control: proves the list makes the pipe form lose, so the tests below could have failed."""
    done = _bash( BIG_SETUP + 'set -o pipefail; printf "%s\\n" "$BIG" | grep -Fxq -- lupin-rest-test; echo rc=$?' )
    assert "rc=0" not in done.stdout, "the pipe form survived; the list is too short to force SIGPIPE here"


def test_overlay_present_survives_pipefail_when_grep_matches_early():
    done = _bash( BIG_SETUP + 'set -o pipefail; source "$LIB"; pfv_overlay_present "$BIG" lupin-rest-test; echo rc=$?' )
    assert done.stdout.strip().endswith( "rc=0" ), done.stdout + done.stderr


def test_cron_status_survives_pipefail_when_grep_matches_early():
    line = "0 3 * * * x vector-refresh cron y # reuse-vector-refresh"
    done = _bash( BIG_SETUP + f'set -o pipefail; source "$LIB"; T="{line}\n$BIG"; pfv_cron_status "$T"; echo " rc=$?"' )
    assert done.stdout.strip() == "PRESENT rc=0", done.stdout + done.stderr


def test_every_printf_fed_grep_q_in_the_vm_scripts_reads_through_a_here_string():
    """Census: no `printf '%s\\n' "$x" | grep -q...` remains in the three VM scripts."""
    hits = []
    for rel in SCRIPTS:
        for n, text in enumerate( open( f"{ROOT}/{rel}" ).read().split( "\n" ), 1 ):
            if PRINTF_PIPE_GREP_Q.search( text ): hits.append( f"{rel}:{n}: {text.strip()}" )
    assert not hits, "printf piped into grep -q (SIGPIPE race under pipefail):\n" + "\n".join( hits )


def test_the_census_pattern_finds_the_old_shape():
    """Control: the pattern matches each shape that was fixed, so a zero above means none remain."""
    for old in [ """printf '%s\\n' "$CONTRACT_NAMES" | grep -qxF "$ev_name" || die""",
                 """printf '%s\\n' "${1:-}" | grep -Fxq -- "$2\"""",
                 """printf '%s\\n' "$running_mounts" | grep -qx "/home/x" && y=true""" ]:
        assert PRINTF_PIPE_GREP_Q.search( old ), old
