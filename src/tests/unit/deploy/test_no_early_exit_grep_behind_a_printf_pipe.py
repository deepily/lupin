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


# Any producer, any option order: `... | grep -q`, `| grep -E -q`, `| sudo grep --quiet`.
ANY_PIPE_GREP_Q = re.compile( r"""\|\s*(?:sudo\s+(?:-n\s+)?)?grep\s+(?:-\S+\s+)*(?:-[A-Za-z]*q[A-Za-z]*|--quiet|--silent)\b""" )


def _pipefail_scripts():
    """Tracked src/scripts files that set pipefail (from git), plus the sourced VM lib."""
    tracked = subprocess.run( [ "git", "-C", ROOT, "ls-files", "src/scripts" ], capture_output=True, text=True, check=True ).stdout.split()
    found   = [ rel for rel in tracked if os.path.isfile( f"{ROOT}/{rel}" ) and "pipefail" in open( f"{ROOT}/{rel}", errors="replace" ).read() ]
    # The lib sets no option itself, but is sourced into scripts that do, so it runs under pipefail.
    return found + [ rel for rel in SCRIPTS if rel not in found ]


def test_the_pipefail_population_is_found_and_names_the_scripts_that_matter():
    """Control: the census walks a real population, not an empty loop."""
    found = _pipefail_scripts()
    assert len( found ) >= 40, len( found )
    for rel in SCRIPTS + [ "src/scripts/hook-link-tick.sh", "src/scripts/tfe_to_cc_matrix.sh", "src/scripts/orphan-sweep-tick.sh", "src/scripts/start-cc-with-tmux.sh" ]:
        assert rel in found, rel


def test_every_pipe_into_grep_q_in_every_pipefail_script_reads_through_a_here_string():
    """Census: no `<any producer> | grep -q` remains in a pipefail script."""
    hits = []
    for rel in _pipefail_scripts():
        for n, text in enumerate( open( f"{ROOT}/{rel}", errors="replace" ).read().split( "\n" ), 1 ):
            if text.lstrip().startswith( "#" ): continue
            if ANY_PIPE_GREP_Q.search( text ): hits.append( f"{rel}:{n}: {text.strip()}" )
    assert not hits, "pipe into grep -q (SIGPIPE race under pipefail):\n" + "\n".join( hits )


def test_the_any_producer_pattern_finds_each_command_fed_shape_that_was_fixed():
    """Control: the pattern matches every shape this row fixed, and spares a here-string."""
    for old in [ """sudo docker ps -a --format '{{.Names}}' | grep -Fxq $TEST_REST_SERVICE; then""",
                 """sudo -n git config --global --get-all safe.directory 2>/dev/null | grep -qxF "$d"; then""",
                 """docker exec "$C" id -G 2>/dev/null | tr ' ' '\\n' | grep -qx "$G" \\""",
                 """if env | grep -q '^VERTEX_REGION_CLAUDE_5_OPUS='; then""",
                 """crontab -l 2>/dev/null | grep -Fq "$TAG"; then""",
                 """x | grep -E -q foo""", """x | grep --quiet foo""" ]:
        assert ANY_PIPE_GREP_Q.search( old ), old
    assert not ANY_PIPE_GREP_Q.search( """grep -qx "$C" <<< "$names" \\""" )
    assert not ANY_PIPE_GREP_Q.search( """printf '%s\\n' "$r" | grep -m1 '^D=' | cut -d= -f2-""" )


def test_command_fed_pipe_form_loses_and_here_string_form_survives_a_failing_early_match():
    """Behaviour: the pipe form loses an early match; the here-string form keeps it."""
    pipe = _bash( 'set -o pipefail; { echo lupin-rest-test; yes yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy | head -n 20000; } | grep -Fxq -- lupin-rest-test; echo rc=$?' )
    assert "rc=0" not in pipe.stdout, "the command-fed pipe survived; the producer is too short to force SIGPIPE here"
    here = _bash( 'set -o pipefail; N="$( echo lupin-rest-test; yes yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy | head -n 20000 )"; grep -Fxq -- lupin-rest-test <<< "$N"; echo rc=$?' )
    assert here.stdout.strip() == "rc=0", here.stdout + here.stderr
    empty = _bash( 'set -o pipefail; N="$( false )"; grep -Fxq -- lupin-rest-test <<< "$N"; echo rc=$?' )
    assert empty.stdout.strip() == "rc=1", "a failed producer must read as no match: " + empty.stdout
