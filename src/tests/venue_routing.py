"""
Venue routing — make the `Venue:` declaration MECHANICAL (row `dba10ba5`).

THE DEFECT THIS CLOSES
----------------------
186 files under `src/tests/` declare a venue in their own docstring
(`Venue: :7999-eligible …`, `Venue: :8000 (monopolize) …`). **Nothing read those
lines.** `run-unit-tests.sh` execs `pytest src/tests/unit/` and the scheduled tier
runs it inside `lupin-rest-test`. The declaration was documentation; the routing
was a directory.

For most tests that gap is harmless — `:7999-eligible` means "cheap and safe",
and cheap-and-safe code runs fine in a container. It is NOT harmless for a test
whose SUBJECT is the host it runs on:

    test_pilot_ac_instruments::test_every_ac_register_entry_matches_the_host
        "⚠️  IT MEANS 'THE TOOL IS ON THIS HOST.'"
        "VERIFIED ON THIS HOST, 2026-07-13"

That register attests that the operator host which will run a metered-billing
pilot carries `gcloud`/`bq`. In the container they are absent, so it goes red —
correctly, for a claim that was never about the container. Installing the
binaries to clear the red would turn a test named `..._matches_the_host` GREEN
while the proposition it encodes went unverified. Ruled 2026-07-27: do not.

⇒ So the tier carried permanent reds for a correct reason, which is precisely the
condition that trains a reader to stop reading a tier (`b5b6d252`).

WHAT THIS DOES INSTEAD
----------------------
`host_only` is declared AT THE TEST, and where the host is unreachable the test
is deselected and **named in the output**. Not counted — NAMED.

⚠️ A COUNT OF DESELECTIONS CANNOT DISTINGUISH "the venue split is working" from
"half my markers are typo'd." Only the SET can. `--strict-markers` (pytest.ini)
makes a typo'd marker a hard error rather than a silent no-op, and
`test_venue_routing.py` pins deselect-set == marker-set.

⛔ NOT A ROSTER. There is deliberately no central list of host-only modules here.
A hand-kept roster is the `_PG_ISOLATION_MODULES` shape that was deleted on
2026-07-27: every new offender is un-covered by default and nothing says so. The
marker travels with the test, so a test cannot be added without declaring, and a
test cannot be moved away from its declaration.
"""
import os


HOST_ONLY_MARKER = "host_only"


def host_is_reachable( dockerenv_path="/.dockerenv" ):
    """
    Ensures:
        - True when this process can observe the operator host's toolchain
        - False inside a container, where the host's PATH is not visible

    `/.dockerenv` is created by the runtime, not by our compose file, so this is
    not a flag anyone has to remember to set — the failure mode of an env-var
    switch is that it silently defaults to the permissive branch.
    """
    return not os.path.exists( dockerenv_path )


def partition_by_venue( items, host_reachable ):
    """
    Split collected items into (kept, deselected) on the host_only marker.

    Requires:
        - items is an iterable of objects exposing .get_closest_marker( name )
        - host_reachable is a bool

    Ensures:
        - host_reachable True  -> nothing is deselected; every item is kept
        - host_reachable False -> exactly the host_only-marked items are deselected
        - the two returned lists partition `items` (no loss, no duplication)
    """
    if host_reachable:
        return list( items ), []

    kept, deselected = [], []
    for item in items:
        if item.get_closest_marker( HOST_ONLY_MARKER ) is None: kept.append( item )
        else:                                                   deselected.append( item )
    return kept, deselected


def deselection_report( deselected_ids ):
    """
    Ensures:
        - returns None when nothing was deselected (no banner for a no-op)
        - otherwise returns a block naming EVERY deselected node-id

    The names are the point. A line reading "7 tests deselected" is satisfied
    just as well by seven correctly-routed tests as by seven typos, and a reader
    cannot tell which. `b5b6d252` lost six tmux-gated assertions for days to
    exactly that: they were skipped, the skip emitted no failure block, and the
    only thing anyone saw was a number that did not move.
    """
    if not deselected_ids: return None
    lines = [
        "",
        "VENUE ROUTING — host_only tests DESELECTED (the host is not reachable from here).",
        "These did NOT run. They are not passes, and this is not a count — here they are:",
    ]
    lines += [ f"    {nid}" for nid in deselected_ids ]
    lines.append(
        "Re-run them where the claim is checkable: pytest -m host_only on the operator host."
    )
    return "\n".join( lines )
