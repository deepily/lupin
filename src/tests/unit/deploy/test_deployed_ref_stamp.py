"""
`lupin-vm.sh` must stamp `.deployed-ref` whenever the VM's working tree MOVES,
and `preflight-vm.sh` must notice when the stamp and the tree disagree —
row c41ec7e6.

THE DEFECT
----------
The code-sync design (src/rnd/v0.1.9/2026.06.23-gcp-code-sync-to-runtime-design.md §3)
promised a provenance stamp so that "what is running on the VM?" is one `cat`,
not a code-grep. Only `deploy-cloud-test.sh` ever wrote it — and that was not the
script this VM is deployed with (it was retired 2026-08-26, row 0d175dac).
`lupin-vm.sh push-bundle` moves the tree in both its moving modes and wrote
nothing.

Measured on the live VM 2026-08-24:

    .deployed-ref   df611aa7 2026-07-13T01:55:12Z code+codeless-image
    actual HEAD     1959ed18                            (1257 commits later)

A stamp five weeks behind is worse than no stamp, because an absent file sends
the reader to measure and a stale one sends them to a wrong answer they have no
reason to doubt.

IT WAS NOT ONLY A DOCUMENTATION DEFECT
--------------------------------------
`deploy-cloud-test.sh` TOOK its axis-detect BASELINE from this file. With the live
stale value, a pure code change was routed to a full image rebuild:

    dctl_detect_axis 1959ed18 dc4b655d  ->  code    (true baseline)
    dctl_detect_axis df611aa7 dc4b655d  ->  deps    (stale stamp)

⚠️ PAST TENSE SINCE 2026-08-26 (row 0d175dac): that script and its `dctl_detect_axis`
were retired, and nothing replaced the detector — so this second consequence no
longer has a mechanism. It is kept as the record of why the check was built. The
FIRST consequence is unchanged and is what B6 still guards: a stale stamp sends the
reader to a wrong answer they have no reason to doubt.

That pair is asserted below, so the claim in preflight's B6 comment is checked
rather than merely written down.

PREVENTION HERE, DETECTION IN PREFLIGHT — AND BOTH ARE NEEDED
-------------------------------------------------------------
The stamp in `do_push_bundle` stops the drift being created. `preflight-vm.sh`
check B6 finds drift that exists anyway — a hand-run `git checkout` on the VM, a
restored snapshot, a deploy from before this change. This mirrors the
purge/B5 pairing in test_pyc_purge_on_checkout.py, for the same reason: a
prevention that is never verified is not a guard.

TWO KINDS OF ARM, AND THE SECOND IS THE ONE THAT MATTERS
--------------------------------------------------------
The shape half asserts the stamp is defined ONCE and referenced by BOTH moving
modes, so `checkout` and `reset` cannot drift apart. Shape alone would stay green
if the command itself were nonsense, so the behaviour half EXTRACTS the stamp
command out of the script source and RUNS it against a real temp git repo,
checking the file it produces against that repo's actual HEAD.

Venue: :7999-eligible. No SSH, no gcloud, no network; the extracted command runs
with sudo stripped, against a temp directory.
"""
import os
import pathlib
import re
import subprocess

import pytest


LUPIN_ROOT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] )
SCRIPT     = LUPIN_ROOT / "src/scripts/lupin-vm.sh"
PREFLIGHT  = LUPIN_ROOT / "src/scripts/preflight-vm.sh"
LIB        = LUPIN_ROOT / "src/scripts/lib/preflight-vm-lib.sh"

SOURCE           = SCRIPT.read_text()
PREFLIGHT_SOURCE = PREFLIGHT.read_text()

# The live values measured on lupin-host-test, 2026-08-24. Used as the realistic
# input to the classifier rather than a made-up sha.
LIVE_STALE_LINE = "df611aa7e72f6274bd5f0e003455784249c38034 2026-07-13T01:55:12Z code+codeless-image"
LIVE_VM_HEAD    = "1959ed182bb56a1daefee44fd20caa73ce41077f"


def _rcmd_line( mode_marker ):
    """
    Return the single `rcmd=` assignment line for the mode whose completion marker
    is `mode_marker` (CHECKED_OUT / RESET_CHECKED_OUT).

    Requires:
        - mode_marker appears on exactly one rcmd= line in the script

    Ensures:
        - returns that line verbatim
        - fails rather than returning None, so a downstream `in` check cannot pass
          vacuously. Matched as `echo <marker> ` and not as a bare substring:
          CHECKED_OUT is a suffix of RESET_CHECKED_OUT.
    """
    hits = [ l for l in SOURCE.split( "\n" )
             if l.lstrip().startswith( "rcmd=" ) and f"echo {mode_marker} " in l ]
    assert len( hits ) == 1, f"expected exactly one rcmd= line for {mode_marker}, got {len( hits )}"
    return hits[ 0 ]


def _run_sh( snippet ):
    """Run a bash snippet, returning the CompletedProcess."""
    return subprocess.run( [ "bash", "-c", snippet ], capture_output=True, text=True )


# ══════════════════════════════════════════════════════════════════════════
# Shape — the stamp exists once and both moving modes use it
# ══════════════════════════════════════════════════════════════════════════

def test_the_stamp_is_defined_exactly_once():
    """
    One definition, so `checkout` and `reset` cannot drift into two subtly
    different stamps — the same single-source-of-truth reason do_push_bundle
    exists rather than two copies of the sync.
    """
    assert len( re.findall( r"^\s*local stamp_ref=", SOURCE, re.M ) ) == 1


@pytest.mark.parametrize( "marker", [ "CHECKED_OUT", "RESET_CHECKED_OUT" ] )
def test_every_mode_that_moves_the_tree_stamps( marker ):
    assert "$stamp_ref" in _rcmd_line( marker )


def test_the_fetch_only_path_does_not_stamp():
    """
    push-bundle with no mode updates refs and leaves the working tree ALONE. No
    code moved, so there is nothing new to record — and a fresh timestamp on an
    unchanged tree would assert a deploy that never happened.
    """
    base = [ l for l in SOURCE.split( "\n" ) if l.lstrip().startswith( "local rcmd=" ) ]
    assert len( base ) == 1
    assert "stamp_ref" not in base[ 0 ]


def test_the_stamp_runs_after_the_tree_has_finished_moving():
    """
    Ordering is load-bearing. Stamping BEFORE the checkout would record the sha
    the tree is leaving, which is the exact defect inverted; stamping before the
    purge would claim a deploy that had not finished its cleanup. Because the
    remote command is one &&-chain, a failure anywhere earlier means no stamp is
    written at all — the old value survives, and no move is ever claimed that did
    not complete.
    """
    for marker in ( "CHECKED_OUT", "RESET_CHECKED_OUT" ):
        line = _rcmd_line( marker )
        assert line.index( "checkout -B" ) < line.index( "$purge_pyc" ) < line.index( "$stamp_ref" )


def test_the_stamp_reports_that_it_ran():
    """
    A silent write is an unverifiable one. The marker is what an operator, or a
    later forensic read of the deploy log, uses to tell "stamped" from "never ran".
    """
    definition = re.search( r"^\s*local stamp_ref=.*$", SOURCE, re.M ).group( 0 )
    assert "REF_STAMPED" in definition


def test_dry_run_narration_mentions_the_stamp():
    """
    --dry-run exists to say what a real run would do. A step it omits is a step
    the reader does not know is coming.
    """
    for marker in ( "checkout)", "reset)" ):
        line = [ l for l in SOURCE.split( "\n" )
                 if l.lstrip().startswith( marker ) and "move_desc=" in l ]
        assert len( line ) == 1
        assert ".deployed-ref" in line[ 0 ]


def test_the_axis_field_does_not_impersonate_a_routed_axis():
    """
    deploy-cloud-test.sh's third field recorded which axis its detector ROUTED to
    (`code` / `deps`); that script was retired 2026-08-26 (row 0d175dac).
    push-bundle runs no such detector — it moves source and never touches deps or
    the image. Writing `code` there would claim a routing decision that was never
    made, which is why this stays asserted after the other writer is gone.
    """
    definition = re.search( r"^\s*local stamp_ref=.*$", SOURCE, re.M ).group( 0 )
    assert "push-bundle-$mode" in definition


# ══════════════════════════════════════════════════════════════════════════
# Behaviour — the extracted command writes a stamp that matches the real HEAD
# ══════════════════════════════════════════════════════════════════════════

def _extract_stamp_command():
    """
    Pull the stamp command out of the script SOURCE and make it runnable here.

    Requires:
        - the script defines `local stamp_ref="..."`

    Ensures:
        - applies the ONE level of unescaping bash performs on a double-quoted
          assignment, so `\\$(` in the source becomes the `$(` that actually
          reaches the VM. Without this the extracted command emits a literal
          "$( git ... )" and the test would be exercising a string the deploy
          never sends.
        - returns the command body with `sudo tee` reduced to `tee` and the
          `sudo chown` step dropped (this test is not root and there is no uid
          1001 here); nothing else is rewritten
        - raises AssertionError if the definition cannot be found, so a renamed
          variable fails the test rather than silently testing an empty string

    It is deliberately NOT a re-typed copy of the command — a test that re-types
    the thing it is testing proves only that the author can type twice.
    """
    m = re.search( r'^\s*local stamp_ref="(.+)"\s*$', SOURCE, re.M )
    assert m, "could not find the stamp_ref definition — did it get renamed?"
    cmd = m.group( 1 ).replace( "\\$", "$" )
    cmd = cmd.replace( "sudo tee", "tee" )
    cmd = re.sub( r"&& sudo chown \S+ \S+ ", "", cmd )
    return cmd


def _seed_repo( tmp_path ):
    """A real git repo with one commit; returns ( path, full_sha )."""
    _run_sh( f'cd "{tmp_path}" && git init -q . '
             f'&& git -c user.email=t@t -c user.name=t commit -q --allow-empty -m seed' )
    sha = _run_sh( f'git -C "{tmp_path}" rev-parse HEAD' ).stdout.strip()
    assert len( sha ) == 40
    return tmp_path, sha


@pytest.mark.parametrize( "mode", [ "checkout", "reset" ] )
def test_the_extracted_stamp_records_the_repos_actual_head( tmp_path, mode ):
    """
    The stamp's sha must come from the tree it is describing, read AFTER the move
    — not from the sha the deploy intended to ship. Intent and outcome are the two
    things this file exists to let a reader compare.
    """
    root, sha = _seed_repo( tmp_path )
    cmd = _extract_stamp_command()
    r = _run_sh( f'VM_ROOT="{root}"; safe="-c safe.directory={root}"; mode="{mode}"; '
                 f'cd "{root}"; {cmd}' )
    assert r.returncode == 0, r.stderr
    assert "REF_STAMPED" in r.stdout

    written = ( root / ".deployed-ref" ).read_text().strip()
    fields  = written.split()
    assert len( fields ) == 3, f"expected 3 fields, got {fields!r}"
    assert fields[ 0 ] == sha, "field 1 must be the repo's real HEAD"
    assert re.fullmatch( r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", fields[ 1 ] ), fields[ 1 ]
    assert fields[ 2 ] == f"push-bundle-{mode}"


def test_the_written_stamp_survives_the_reader_that_consumes_it( tmp_path ):
    """
    THE HANDSHAKE with the consumer. A stamp this script writes must be read back
    by the live reader as exactly the sha it recorded — if either side's idea of
    the format drifts, this fails.

    RE-POINTED 2026-08-26 (row 0d175dac). This used to call `dctl_sanitize_sha`,
    which lived in deploy-cloud-test-lib.sh and was retired with that script. The
    surviving consumer is preflight's `pfv_deployed_ref_status`, which does its own
    field-1 extraction — so the handshake is still real, and is now tested against
    the reader that actually runs rather than one that no longer exists.
    """
    root, sha = _seed_repo( tmp_path )
    cmd = _extract_stamp_command()
    _run_sh( f'VM_ROOT="{root}"; safe="-c safe.directory={root}"; mode="checkout"; '
             f'cd "{root}"; {cmd}' )

    line = ( root / ".deployed-ref" ).read_text().strip()
    r = _run_sh( f'source "{LIB}"; pfv_deployed_ref_status "{line}" "{sha}"' )
    assert r.stdout.strip() == "MATCH", r.stdout + r.stderr
    assert r.returncode == 0


# ══════════════════════════════════════════════════════════════════════════
# Detection — preflight B6's classifier
# ══════════════════════════════════════════════════════════════════════════

def _classify( line, head ):
    """Run pfv_deployed_ref_status; return ( stdout, returncode )."""
    r = _run_sh( f'source "{LIB}"; pfv_deployed_ref_status "{line}" "{head}"' )
    return r.stdout.strip(), r.returncode


@pytest.mark.parametrize(
    "line,head,expect,rc",
    [
        ( "",                                                              "a" * 40, "ABSENT",    2 ),
        ( "b" * 40 + " 2026-08-24T00:00:00Z push-bundle-checkout",         "a" * 40, "STALE",     1 ),
        ( "a" * 40 + " 2026-08-24T00:00:00Z push-bundle-checkout",         "a" * 40, "MATCH",     0 ),
        ( "aaaaaaa 2026-08-24T00:00:00Z x",                                "a" * 40, "MALFORMED", 3 ),
        ( "not-a-sha 2026-08-24T00:00:00Z x",                              "a" * 40, "MALFORMED", 3 ),
    ],
    ids=[ "absent", "stale", "match", "short-sha", "non-hex" ],
)
def test_the_classifier_names_each_state( line, head, expect, rc ):
    assert _classify( line, head ) == ( expect, rc )


def test_the_classifier_calls_the_LIVE_stale_stamp_stale():
    """
    The defect this row was opened for, replayed through the detector with the
    values measured on the VM. A classifier that only ever sees synthetic input
    has not been shown to catch the thing it was built for.
    """
    assert _classify( LIVE_STALE_LINE, LIVE_VM_HEAD ) == ( "STALE", 1 )


def test_a_prefix_match_is_not_a_match():
    """
    The two live shas share no prefix, so the corpus above cannot catch a
    prefix-compare bug. This plants one: 39 shared characters and a different
    last one must still read STALE.
    """
    head = "a" * 40
    assert _classify( "a" * 39 + "b", head ) == ( "STALE", 1 )


def test_an_uppercase_sha_is_malformed_not_silently_matched():
    """
    `git rev-parse` emits lowercase. An uppercase value came from somewhere else,
    so its claim is not one this check can vouch for — say so rather than
    case-fold it into a pass.
    """
    assert _classify( "A" * 40, "a" * 40 )[ 0 ] == "MALFORMED"


# ══════════════════════════════════════════════════════════════════════════
# Wiring — B6 is actually reachable, and the claim in its comment is true
# ══════════════════════════════════════════════════════════════════════════

def test_preflight_calls_the_classifier():
    """
    A classifier nothing calls is a unit test with no deploy behind it.
    """
    assert "pfv_deployed_ref_status" in PREFLIGHT_SOURCE


def test_b6_handles_every_state_the_classifier_can_return():
    """
    The classifier has four outcomes. A case arm missing one would report NOTHING
    for that state — the silent pass that this whole row is about.
    """
    b6 = PREFLIGHT_SOURCE[ PREFLIGHT_SOURCE.index( "ref_status=" ) : ]
    b6 = b6[ : b6.index( "esac" ) ]
    for state in ( "MATCH", "ABSENT", "MALFORMED", "STALE" ):
        assert f"{state})" in b6, f"B6 has no arm for {state}"


def test_b6_runs_in_the_post_phase_block():
    """
    B6 must sit inside `if layer_runs B`, with B1/B2, for their reason: in the PRE
    phase HEAD is about to move, so asserting the stamp against it would be noise
    that reads as coverage.
    """
    block_start = PREFLIGHT_SOURCE.index( "if layer_runs B; then" )
    block_end   = PREFLIGHT_SOURCE.index( "else note_skip B; fi" )
    assert block_start < PREFLIGHT_SOURCE.index( "pfv_deployed_ref_status" ) < block_end


# RETIRED 2026-08-26 (row 0d175dac): test_the_stale_baseline_really_does_misroute_the_axis.
# It asserted that a stale stamp made deploy-cloud-test.sh's axis detector route a pure
# code change to a full image rebuild. Both the script and its `dctl_detect_axis` were
# retired that day and nothing replaced the detector, so the assertion had no subject.
# B6 is unaffected: its other stated reason -- a stale stamp means the tree moved and was
# never re-stamped -- is still checked, by the tests above.
