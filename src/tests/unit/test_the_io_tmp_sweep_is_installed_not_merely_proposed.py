"""
Guard for row 730b33f2 item 3 — the sweep must be IN `crontab -l`, not just in a file.

🔴 WHY THIS EXISTS, AND WHY THE FILE-BASED GUARD BESIDE IT IS NOT ENOUGH.
`test_a_cron_entry_fires_inside_the_hosts_waking_hours.py` opens
`src/scripts/disk-hygiene.crontab` and asserts what that FILE says. It will stay
green forever with nothing installed on the host. A `.crontab` file is a document
PROPOSING a crontab entry; the row's item 3 asks for a scheduled sweep, and until
the line is in `crontab -l`, io/tmp/ is io/write-ups/ with a shorter name — which
the sweep script's own header names as the exact failure it exists to prevent.

The file itself already carried the warning three lines above the new entry
("⚠️ A .crontab FILE IS NOT AN INSTALLED SWEEP… verify with `crontab -l | grep
sweep-io-tmp`"). The warning was right and the test checked the other thing.
Caught by Rachel 🕊️ in review, 2026-09-26. A doc that is half machine-checked is
the worst of both: the checked half earns trust the unchecked half then spends.

AND IT IS NOT HYPOTHETICAL FOR THE NEIGHBOURS EITHER. Rachel measured that the two
Sunday disk-hygiene entries HAVE been in `crontab -l` since 2026-08-23 and have
still never run — their log files do not exist and 03:00 falls outside every
recent boot. So "installed" and "running" are two different claims, and this file
only makes the first. The second is the schedule guard's job.

⚠️ EXPECTED TO BE RED UNTIL SOMEONE INSTALLS IT. Whoever merges runs the install
line at the top of src/scripts/disk-hygiene.crontab. This test going green IS the
receipt that it happened; that is the point of writing it rather than trusting a
step in a hand-off message.

THE INSTRUMENT IS CONTROLLED. Every case first proves `crontab -l` returned a
listing it can see entries in, by finding a line known to be present. A grep over
an empty or unreadable listing returns zero for the same reason a genuinely
missing entry does, and reporting one as the other is the failure this project has
already paid for twice today.

VENUE: :7999. Reads the invoking user's crontab, writes nothing, sub-second.
"""

import shutil
import subprocess

import pytest

# A line known to be in this host's crontab, used ONLY as a positive control.
# If it ever goes away, these tests skip loudly rather than passing or failing on
# an instrument nobody has watched work.
CONTROL_NEEDLE = "context-pressure-tick.sh"


def _crontab_lines():
    """
    Return the invoking user's crontab as a list of lines.

    Ensures:
        - returns [] when crontab is absent from PATH or exits non-zero
    """
    if shutil.which( "crontab" ) is None: return []
    result = subprocess.run( [ "crontab", "-l" ], capture_output=True, text=True, timeout=60 )
    if result.returncode != 0: return []
    return result.stdout.splitlines()


@pytest.fixture( scope="module" )
def crontab_listing():
    """
    The listing, with the instrument proven before anything is concluded from it.

    Ensures:
        - returns the full list of lines
        - SKIPS (never passes, never fails) when the control line is absent, because
          a zero from a listing we cannot read says nothing about the sweep
    """
    lines = _crontab_lines()
    if not any( CONTROL_NEEDLE in ln for ln in lines ):
        pytest.skip(
            f"positive control {CONTROL_NEEDLE!r} not found in `crontab -l` "
            f"({len( lines )} lines read) — the instrument is not proven, so a zero "
            "for the sweep would be a silence rather than a measurement"
        )
    return lines


def test_the_sweep_is_actually_in_the_users_crontab( crontab_listing ):
    hits = [ ln for ln in crontab_listing if "sweep-io-tmp.sh" in ln and not ln.lstrip().startswith( "#" ) ]
    assert hits, (
        "row 730b33f2 item 3 is NOT satisfied: no uncommented sweep-io-tmp.sh line in "
        "`crontab -l`. A line in src/scripts/disk-hygiene.crontab is a document proposing "
        "a crontab entry — until it is installed, io/tmp/ never clears and the folder is "
        "io/write-ups/ with a shorter name.\n"
        "Install: crontab -l > /tmp/c; cat src/scripts/disk-hygiene.crontab >> /tmp/c; crontab /tmp/c"
    )


def test_the_installed_line_carries_apply( crontab_listing ):
    """
    María's gate, checked where it counts. The FILE having --apply says nothing
    about what is installed — an older copy could have been installed before the
    flag was added, and it would dry-run nightly forever.
    """
    hits = [ ln for ln in crontab_listing if "sweep-io-tmp.sh" in ln and not ln.lstrip().startswith( "#" ) ]
    if not hits: pytest.skip( "covered by test_the_sweep_is_actually_in_the_users_crontab" )
    for ln in hits:
        assert "sweep-io-tmp.sh --apply" in ln, (
            f"an installed sweep line without --apply can only ever dry-run: {ln!r}"
        )


def test_the_installed_daily_line_is_not_in_the_dead_window( crontab_listing ):
    """
    The schedule guard next door asserts this about the FILE. What runs is what is
    installed, and the two can differ by exactly one stale install.
    """
    hits = [
        ln for ln in crontab_listing
        if "sweep-io-tmp.sh" in ln and not ln.lstrip().startswith( "#" ) and not ln.startswith( "@" )
    ]
    if not hits: pytest.skip( "covered by test_the_sweep_is_actually_in_the_users_crontab" )
    for ln in hits:
        hour = int( ln.split()[ 1 ] )
        assert 19 <= hour <= 20, (
            f"the INSTALLED sweep fires at {hour}:00, outside the host's observed waking "
            f"hours (19:00-20:59 — latest boot start 18:12, earliest completed-boot end "
            f"20:13, measured 2026-09-26 over 20 boots). It will not run late; it will not "
            f"run: {ln!r}"
        )


def test_the_reboot_catch_up_arm_is_installed_too( crontab_listing ):
    hits = [
        ln for ln in crontab_listing
        if ln.startswith( "@reboot" ) and "sweep-io-tmp.sh" in ln
    ]
    assert hits, (
        "the @reboot catch-up arm is not installed — a day the host is down at 19:00 then "
        "skips a whole cycle instead of sweeping at the next power-on"
    )
