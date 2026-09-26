"""
Guard for `src/scripts/disk-hygiene.crontab` — row 730b33f2.

🔴 A CRON JOB SCHEDULED WHILE THE BOX IS OFF IS NOT A LATE JOB, IT IS NO JOB, AND
IT LOOKS EXACTLY LIKE A WORKING ONE. Nothing errors, no log line appears, and the
absence of output is indistinguishable from a clean sweep with nothing to do.

THIS IS NOT HYPOTHETICAL AND IT IS NOT SOMEONE ELSE'S MISTAKE. The io/tmp sweep
was first written at 04:00 daily — a time chosen to stay clear of the two jobs
above it, with no thought given to whether the host is up. Mr. Radio caught it on
review. Re-derived from `journalctl --list-boots --no-pager` on 2026-09-26, twenty
boots spanning 2026-09-04 to 2026-09-26:

    latest a boot BEGAN  : 18:12
    earliest a boot ENDED: 20:13   (completed boots only)

so 19:00 is the one hour inside every boot window in the sample, and 04:00 is
inside none of them. CLAUDE.md § Off-peak scheduling already said ~11 PM-10 AM is
dead and that this is a constraint rather than a record of habit. The rule was
written down and it was not installed, so this file installs it.

The two pre-existing Sunday entries (María's, 2026-08-23) were in the dead window
too, at 03:00 and 03:30, and had never fired. They were carried in a PENDING_RULING
exemption list until row 77422be2 moved them to 19:00/19:30 on Rick's ruling
(2026-09-26). The list and its stale-entry check were then deleted rather than left
empty, because an empty list's check cannot fail (Rachel's review). Every timed
entry is now held to the window, and a future exemption has to come back as code.

VENUE: :7999. Reads one file from the repo, writes nothing, sub-second.
"""

import re

import cosa.utils.util as cu

CRONTAB = cu.get_project_root() + "/src/scripts/disk-hygiene.crontab"

# The host-up window, derived above. A job must fire at an hour inside it.
HOST_UP_FIRST_HOUR = 19   # latest observed boot start was 18:12
HOST_UP_LAST_HOUR  = 20   # earliest observed completed-boot end was 20:13


def _entries():
    """
    Parse the crontab file into (schedule, command) pairs.

    Ensures:
        - returns a list of ( schedule_str, command_str )
        - comment and blank lines are dropped
        - `@reboot` and friends come back with the schedule field "@reboot"
    """
    out = []
    with open( CRONTAB ) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith( "#" ): continue
            if line.startswith( "@" ):
                sched, _, cmd = line.partition( " " )
                out.append( ( sched, cmd.strip() ) )
                continue
            parts = line.split( None, 5 )
            assert len( parts ) == 6, f"unparseable crontab line: {line!r}"
            out.append( ( " ".join( parts[ :5 ] ), parts[ 5 ] ) )
    return out


def test_the_file_parses_into_entries_at_all():
    """
    Assert the loop below has something to loop over.

    A loop over nothing passes every assertion inside it, and a parser that
    silently matched zero lines would make every case in this file vacuous.
    """
    entries = _entries()
    assert len( entries ) >= 3, f"expected at least 3 cron entries, parsed {len( entries )}: {entries}"


def test_every_timed_entry_fires_while_the_host_is_awake():
    offenders = []
    for sched, cmd in _entries():
        if sched.startswith( "@" ):        continue   # @reboot runs at power-on by definition
        hour = int( sched.split()[ 1 ] )
        if not ( HOST_UP_FIRST_HOUR <= hour <= HOST_UP_LAST_HOUR ):
            offenders.append( ( sched, hour, cmd[ :70 ] ) )
    assert not offenders, (
        "cron entries scheduled outside the host's observed waking hours "
        f"({HOST_UP_FIRST_HOUR}:00-{HOST_UP_LAST_HOUR}:59). These do not run LATE — they do "
        f"not run at all, and they look identical to a job with nothing to do:\n{offenders}"
    )


def test_the_io_tmp_sweep_has_a_catch_up_arm_for_a_day_the_box_was_off():
    reboot_cmds = [ cmd for sched, cmd in _entries() if sched == "@reboot" ]
    assert any( "sweep-io-tmp.sh" in c for c in reboot_cmds ), (
        "a daily-only sweep skips a whole cycle on a day the host is down at 19:00; "
        f"@reboot is the catch-up. @reboot entries found: {reboot_cmds}"
    )


def test_the_crontab_entry_actually_applies():
    """
    María's gate, 2026-09-26: the sweep dry-runs by DEFAULT. A cron line without
    `--apply` prints an eligible count forever and deletes nothing — a janitor
    that reports for duty every night and never picks anything up.
    """
    sweep_lines = [ ( sched, cmd ) for sched, cmd in _entries() if "sweep-io-tmp.sh" in cmd ]
    assert sweep_lines, "no io/tmp sweep entry in the crontab file at all"
    for sched, cmd in sweep_lines:
        assert "sweep-io-tmp.sh --apply" in cmd, (
            f"the {sched!r} entry invokes the sweep WITHOUT --apply, so it can only "
            f"ever dry-run: {cmd!r}"
        )


def test_every_entry_pins_lupin_root():
    """
    The sweep refuses without LUPIN_ROOT, so an entry missing it fails nightly —
    into a log nobody reads, which is the same silence as not running.
    """
    for sched, cmd in _entries():
        assert re.search( r"\bLUPIN_ROOT=/", cmd ), f"{sched!r} entry does not pin LUPIN_ROOT: {cmd!r}"


def test_every_entry_redirects_both_streams_to_a_log():
    """
    `2>&1` and not just `>>`. Without it stderr goes to cron's mailer, which on
    this box goes nowhere — the failure mode that makes a broken job look quiet
    rather than broken.
    """
    for sched, cmd in _entries():
        assert ">>" in cmd and "2>&1" in cmd, f"{sched!r} entry does not capture both streams: {cmd!r}"
