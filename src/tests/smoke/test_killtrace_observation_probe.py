"""
AC5 (addendum) / AC6 benign canary — the killtrace instrument observes
kill-server events END-TO-END, proven on an isolated socket.

Spins a throwaway tmux server on a private -S socket from a $TMUX-stripped
env, kill-servers THAT server, and awaits the expected killtrace line for
its pid. The observed sig=15 self-SIGTERM (sender == target == server pid)
ALSO empirically confirms the §2.1 signature rule — one probe, two
confirmations.

CONDITIONALITY (ratified AC5 rider): if the root tracer is absent or its log
unreadable by this uid, SKIP WITH A NAMED REASON that requests the install —
never a silent skip.

SAFETY: operates entirely inside §7's hard rule — explicit private -S socket
+ $TMUX-stripped env; no verb here can address the fleet default socket.

VENUE: :7999-eligible / AI-discretionary — throwaway server, seconds.
"""

import os
import shutil

import pytest

from tests.smoke.utilities.killtrace_probe import KILLTRACE_LOG, run_probe


pytestmark = pytest.mark.skipif( not shutil.which( "tmux" ), reason="tmux is not installed" )


def test_killtrace_observes_kill_server_on_an_isolated_socket( tmp_path ):
    if not os.access( KILLTRACE_LOG, os.R_OK ):
        pytest.skip(
            f"{KILLTRACE_LOG} absent or unreadable by uid {os.getuid()} — the runbook §10 root "
            f"tracer is not installed (or its log is root-only). REQUEST INSTALL from the user "
            f"per the install-only-on-request contract; this skip is the AC5 named-reason "
            f"fallback, never silent."
        )

    server_pid, line = run_probe( tmp_path / "canary.sock", os.environ, timeout_s=15.0 )

    assert line is not None, (
        f"the killtrace instrument did NOT observe kill-server for throwaway server pid "
        f"{server_pid} within 15s — either the tracer service is dead (check "
        f"`systemctl status tmux-killtrace.service`) or the §2.1 signature rule no longer "
        f"holds. A blind instrument is worse than none: fix before trusting any killtrace null."
    )
    assert f"target={server_pid}" in line and "from=tmux: server" in line, (
        f"unexpected line shape: {line!r} — the §2.1 self-SIGTERM signature "
        f"(sender==target==server) did not confirm."
    )
