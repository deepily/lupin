"""
The guard that guards the guard list.

Design: src/rnd/v0.1.9/2026.07.13-vertex-model-garden-toggle-search-and-logging.md

WHY THIS FILE EXISTS — and it is an indictment of the file it protects.

test_vertex_env.py parametrizes over the whole HOSTILE_ENV_KEYS tuple, and I
described that as "adding a key without a guard is impossible by construction."

That claim is FALSE, and it is false in exactly the shape this cascade has now
killed five times:

    It proves every key IN the tuple is guarded.
    It proves NOTHING about whether the tuple is COMPLETE.

The tuple's completeness rests on a grep of the shipped Claude Code binary at the
release recorded in PER_MODEL_REGION_OVERRIDES_CALIBRATION (the version is NOT
restated here — a restated fact falls behind its source in silence, which is the
same defect one level up) — a POINT-IN-TIME fact about someone else's release
artifact. And it has already moved once: harvested at 2.1.207, re-derived clean
against 2.1.209 on 2026-07-14. The key set held; the version did not. That is
exactly the drift this file exists to notice.

A Claude Code upgrade that ships VERTEX_REGION_CLAUDE_5_OPUS would leave the
tuple silently short by one, the parametrized suite would stay green (it would
faithfully test all fifteen keys it knows about), and a single inherited variable
would route Opus alone to another region — where it RUNS, BILLS, and LOGS NOTHING.

That is F-A8's "mechanically enforced, FOREVER" over a hardcoded list, re-committed
inside the fix for F-A8. A completeness claim that cannot fail is not a guarantee;
it is a wish with good grammar.

So this file DERIVES the truth from the artifact instead of asserting it from
memory: it greps the actual binary and fails when reality and the tuple diverge.

NOTE ON FAILING RATHER THAN SKIPPING: if the binary cannot be found, this test
FAILS. It does not skip. A skipped completeness check and a passing one look
identical in a 9000-test run, and "I could not verify" must never be reported as
"I verified." That is the whole lesson of this cascade, applied to our own harness.

AND THE PART I ALMOST SHIPPED WITHOUT: the paragraph above describes three guards
(fail-on-missing-binary, fail-on-empty-scrape, fail-on-drift), and a described guard
is not a guard. Every one of them is exercised BELOW, against a synthetic binary, so
each is proven to be able to come out otherwise. An instrument that has never been
seen to fail is not an instrument; it is a decoration that has never been asked a
question it could get wrong.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from cosa.utils.vertex_env import (
    HOSTILE_ENV_KEYS,
    PER_MODEL_REGION_OVERRIDES,
    PER_MODEL_REGION_OVERRIDES_CALIBRATION,
)


PER_MODEL_REGION_PATTERN = re.compile( rb"VERTEX_REGION_CLAUDE_[A-Z0-9_]+" )


def _resolve_claude_binary():
    """
    Locate the shipped Claude Code binary — the ground truth for the override set.

    Ensures:
        - returns a Path to the real binary (symlinks resolved)

    Raises:
        - AssertionError (fail loud) if it cannot be found, because an unverifiable
          completeness claim is exactly the defect this file exists to prevent
    """
    which = shutil.which( "claude" )
    assert which, (
        "Cannot locate the `claude` binary, so the hostile-key set CANNOT BE VERIFIED "
        "against ground truth. This test FAILS rather than skips on purpose: a skipped "
        "completeness check and a passing one are indistinguishable in a large run, and "
        '"I could not verify" must never be reported as "I verified."'
    )
    return Path( which ).resolve()


def _resolve_claude_version( binary_path ):
    """
    Report the running Claude Code version — DIAGNOSTIC ONLY, never a guard.

    It is deliberately not compared to the calibration: an upgrade that leaves the key
    set alone is a VALID configuration, and a check that reddens on a valid configuration
    is the C4 bug (it teaches people to disable guards). This exists so that when the DRIFT
    guard fires, the failure names the release that moved underneath us instead of leaving
    the reader to go find it.

    Requires:
        - binary_path points at the resolved claude binary

    Ensures:
        - returns the reported version string, or an explicit UNRESOLVED marker — it NEVER
          raises, because a diagnostic that can break the test it annotates is a liability
    """
    try:
        result = subprocess.run(
            [ str( binary_path ), "--version" ], capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip() or f"UNRESOLVED (no output from {binary_path})"
    except ( OSError, subprocess.SubprocessError ) as error:
        return f"UNRESOLVED ({type( error ).__name__}: {error})"


def _scrape_per_model_region_overrides( binary_path ):
    """
    Extract every VERTEX_REGION_CLAUDE_* key the shipped binary actually honors.

    Requires:
        - binary_path points at an existing file

    Ensures:
        - returns a set of decoded key names found in the binary

    Raises:
        - AssertionError if `strings` is unavailable — the instrument is missing, which is
          an INSTRUMENT failure and must never be silently downgraded to "found nothing"
        - AssertionError if the scrape returns nothing — a POSITIVE CONTROL. An empty
          result means the instrument is broken (wrong path, packed binary, changed
          encoding), NOT that the binary honors no overrides. A null is not evidence
          until you prove the instrument can speak.
    """
    try:
        raw = subprocess.run( [ "strings", str( binary_path ) ], capture_output=True )
    except FileNotFoundError as error:
        raise AssertionError(
            f"`strings` is not available, so the override tuple CANNOT BE VERIFIED against the "
            f"shipped binary ({error}). This is an INSTRUMENT failure, and it fails loud: an "
            f"unverifiable completeness claim must never be reported as a verified one. Install "
            f"binutils, or run this suite where the instrument exists."
        ) from error

    found = { match.decode() for match in PER_MODEL_REGION_PATTERN.findall( raw.stdout ) }

    assert found, (
        f"Scraped ZERO VERTEX_REGION_CLAUDE_* keys from {binary_path}. That is an INSTRUMENT "
        "FAILURE, not a finding: it means this test can no longer see what it is meant to "
        "check. Treating it as 'no overrides exist' would be reading absence-of-output as "
        "absence-of-the-thing — the founding bug of this entire design."
    )
    return found


def _assert_tuple_matches_binary( binary_path, guarded ):
    """
    THE DRIFT GUARD, taking its binary as an ARGUMENT so it can be aimed at a synthetic one.

    That parameter is the whole point: a guard you can only run against the passing case has
    never been shown to be able to fail. Aimed at the real binary it is the completeness check;
    aimed at a fake binary carrying an unknown key, it is the proof that the check works.

    Requires:
        - binary_path points at a file `strings` can read
        - guarded is the set of keys vertex_env.py enforces

    Ensures:
        - returns None when the binary's override set is exactly the guarded set

    Raises:
        - AssertionError naming the UNGUARDED keys (the dangerous direction — the binary
          honors a key we do not scrub) or the PHANTOM keys (the stale direction — we scrub
          a key the binary no longer honors, and a stale guard list is a lying one)
    """
    actual  = _scrape_per_model_region_overrides( binary_path )
    version = _resolve_claude_version( binary_path )

    unguarded = actual - guarded
    phantom   = guarded - actual

    assert not unguarded, (
        f"{binary_path} [{version}] honors per-model region overrides that vertex_env.py DOES "
        f"NOT GUARD: {sorted( unguarded )}. Each one silently routes a SINGLE model to another "
        f"region, where it runs, bills, and logs nothing while every other model behaves "
        f"normally. The tuple was harvested from CC {PER_MODEL_REGION_OVERRIDES_CALIBRATION[ 'cc_version' ]} "
        f"on {PER_MODEL_REGION_OVERRIDES_CALIBRATION[ 'harvested' ]}; the release above has moved. "
        f"Add them to PER_MODEL_REGION_OVERRIDES and re-stamp the calibration."
    )

    assert not phantom, (
        f"vertex_env.py guards keys {binary_path} [{version}] no longer honors: {sorted( phantom )}. "
        "Harmless to security, but a stale guard list is a lying guard list — and the next reader "
        "will trust it. Remove them and re-stamp the calibration."
    )


def test_per_model_region_override_set_matches_the_shipped_binary():
    """
    THE COMPLETENESS GUARD, aimed at the REAL binary. Derives the override set from the
    shipped artifact and fails when it diverges from the tuple our guards enforce.

    A Claude Code upgrade that adds a per-model region override will turn this RED — which
    is the only reason the parametrized guard suite can honestly claim coverage.
    """
    _assert_tuple_matches_binary( _resolve_claude_binary(), set( PER_MODEL_REGION_OVERRIDES ) )


# ---------------------------------------------------------------------------
# THE INSTRUMENT TESTS — proof that every guard above CAN COME OUT OTHERWISE.
#
# Without these, "the scrape fails rather than skips" is a sentence in a docstring,
# and this cascade has now killed five guards whose only existence was a sentence.
# ---------------------------------------------------------------------------

def _fake_binary( tmp_path, keys, name="fake-claude" ):
    """Write a synthetic 'binary' whose only readable strings are the given keys."""
    fake = tmp_path / name
    fake.write_bytes( b"\x7fELF padding " + b" ".join( key.encode() for key in keys ) + b" tail" )
    return fake


def test_the_scrape_finds_keys_in_a_synthetic_binary( tmp_path ):
    """
    POSITIVE CONTROL FIRST. Every refusal below is unattributable until the instrument has
    been SEEN to speak: if the regex or the `strings` call were broken, an empty scrape would
    look exactly like "this binary honors no overrides."
    """
    fake  = _fake_binary( tmp_path, [ "VERTEX_REGION_CLAUDE_4_8_OPUS", "VERTEX_REGION_CLAUDE_5_OPUS" ] )
    found = _scrape_per_model_region_overrides( fake )

    assert found == { "VERTEX_REGION_CLAUDE_4_8_OPUS", "VERTEX_REGION_CLAUDE_5_OPUS" }


def test_the_drift_guard_goes_red_when_the_binary_ships_an_unguarded_override( tmp_path ):
    """
    THE ONE THAT MATTERS. A future CC that ships VERTEX_REGION_CLAUDE_5_OPUS — the key the
    tuple conspicuously lacks — must turn this suite RED. Proven here against a synthetic
    release, because waiting for the real one to arrive is not a test strategy.
    """
    fake = _fake_binary( tmp_path, list( PER_MODEL_REGION_OVERRIDES ) + [ "VERTEX_REGION_CLAUDE_5_OPUS" ] )

    with pytest.raises( AssertionError ) as exc:
        _assert_tuple_matches_binary( fake, set( PER_MODEL_REGION_OVERRIDES ) )

    assert "VERTEX_REGION_CLAUDE_5_OPUS" in str( exc.value )
    assert "DOES NOT GUARD"              in str( exc.value )


def test_the_drift_guard_goes_red_on_a_stale_phantom_key( tmp_path ):
    """The other direction: we guard a key the binary dropped. A stale guard list lies."""
    survivors = [ key for key in PER_MODEL_REGION_OVERRIDES if key != "VERTEX_REGION_CLAUDE_3_5_HAIKU" ]
    fake      = _fake_binary( tmp_path, survivors )

    with pytest.raises( AssertionError ) as exc:
        _assert_tuple_matches_binary( fake, set( PER_MODEL_REGION_OVERRIDES ) )

    assert "VERTEX_REGION_CLAUDE_3_5_HAIKU" in str( exc.value )
    assert "no longer honors"               in str( exc.value )


def test_an_empty_scrape_fails_loud_instead_of_reporting_no_overrides( tmp_path ):
    """
    A binary `strings` can read but which yields nothing is an INSTRUMENT failure — a packed
    binary, a changed encoding, the wrong path. Reading absence-of-output as absence-of-the-
    thing is the founding bug of this entire design, so it fails rather than passing quietly.
    """
    empty = tmp_path / "empty-claude"
    empty.write_bytes( b"" )

    with pytest.raises( AssertionError, match="INSTRUMENT" ):
        _scrape_per_model_region_overrides( empty )


def test_a_missing_binary_fails_loud_rather_than_skipping( monkeypatch ):
    """
    THE ANTI-SKIP GUARD. In a container with no `claude` on PATH, this file must go RED, not
    green-with-a-skip: a skipped completeness check and a passing one are indistinguishable
    in a 9,000-test run, and "I could not verify" must never be reported as "I verified."
    """
    monkeypatch.setattr( shutil, "which", lambda _name: None )

    with pytest.raises( AssertionError, match="CANNOT BE VERIFIED" ):
        _resolve_claude_binary()


def test_a_missing_strings_instrument_fails_loud( monkeypatch, tmp_path ):
    """No `strings` means no ground truth. That is an instrument failure, not a clean bill."""
    def _no_strings( *_args, **_kwargs ):
        raise FileNotFoundError( 2, "No such file or directory: 'strings'" )

    monkeypatch.setattr( subprocess, "run", _no_strings )

    with pytest.raises( AssertionError, match="`strings` is not available" ):
        _scrape_per_model_region_overrides( tmp_path / "whatever" )


def test_the_calibration_records_the_release_the_tuple_was_harvested_from():
    """
    C3's RECORD (not its guard). The tuple is a point-in-time scrape of someone else's release
    artifact, and a harvest without a date is a claim without a provenance. The guard is the
    re-derivation above; this only ensures the red message can say WHAT MOVED.
    """
    assert PER_MODEL_REGION_OVERRIDES_CALIBRATION[ "cc_version" ]
    assert PER_MODEL_REGION_OVERRIDES_CALIBRATION[ "harvested"  ]
    assert "VERTEX_REGION_CLAUDE" in PER_MODEL_REGION_OVERRIDES_CALIBRATION[ "instrument" ]


def test_the_version_probe_reports_the_running_release():
    """The diagnostic must actually diagnose — otherwise the red message annotates nothing."""
    assert "UNRESOLVED" not in _resolve_claude_version( _resolve_claude_binary() )


def test_the_version_probe_never_raises_and_degrades_explicitly( monkeypatch, tmp_path ):
    """
    A DIAGNOSTIC MUST NOT BE ABLE TO BREAK THE GUARD IT ANNOTATES. If the version probe threw,
    a broken `--version` would redden the drift test for a reason that has nothing to do with
    drift — and the next reader would learn to distrust the one check that matters.
    """
    def _explode( *_args, **_kwargs ):
        raise OSError( "binary is not executable" )

    monkeypatch.setattr( subprocess, "run", _explode )
    assert "UNRESOLVED (OSError" in _resolve_claude_version( tmp_path / "claude" )


def test_the_version_probe_degrades_when_the_binary_says_nothing( monkeypatch, tmp_path ):
    """Silent output is not a version. Say so, rather than annotating the failure with ''."""
    class _Silent:
        stdout = "   \n"

    monkeypatch.setattr( subprocess, "run", lambda *_a, **_k: _Silent() )
    assert "UNRESOLVED (no output" in _resolve_claude_version( tmp_path / "claude" )


def test_hostile_key_set_has_no_duplicates_and_no_empty_entries():
    """A duplicated or empty key silently weakens the scrub list in the shell wrapper."""
    assert all( HOSTILE_ENV_KEYS ), "HOSTILE_ENV_KEYS contains an empty entry"
    assert len( HOSTILE_ENV_KEYS ) == len( set( HOSTILE_ENV_KEYS ) ), (
        "HOSTILE_ENV_KEYS contains duplicates — the `env -u` scrub list and the "
        "parametrized guard suite both iterate it, and a duplicate hides a miscount."
    )


def test_every_hostile_key_is_in_exactly_one_category():
    """
    The ASSERTABLE / UNASSERTABLE split is load-bearing (a key in NEITHER bucket is
    unguarded; a key in BOTH is ambiguous). Prove the partition is total and disjoint.
    """
    from cosa.utils.vertex_env import (
        ASSERTABLE_MODEL_OVERRIDES,
        ASSERTABLE_PROJECT_OVERRIDES,
        ENDPOINT_SUBVERTERS,
        UNASSERTABLE_PROJECT_OVERRIDES,
    )

    # The HOSTILE set is the must-be-ABSENT keys. The ASSERTABLE sets are compared,
    # not banned — so they are deliberately NOT here (C4: banning an agreeing value is
    # a guard that fires on a valid configuration).
    categories = {
        "per_model_region" : set( PER_MODEL_REGION_OVERRIDES ),
        "unassertable"     : set( UNASSERTABLE_PROJECT_OVERRIDES ),
        "endpoint"         : set( ENDPOINT_SUBVERTERS ),
    }

    # Every hostile key belongs to exactly one category (total + disjoint partition).
    union = set()
    for name, keys in categories.items():
        overlap = union & keys
        assert not overlap, f"{name} overlaps a previous category on {sorted( overlap )}"
        union |= keys

    assert union == set( HOSTILE_ENV_KEYS ), (
        "HOSTILE_ENV_KEYS is not exactly the union of its categories — a key belongs to "
        "neither bucket, or the tuple was edited without updating a category."
    )

    # The ASSERTABLE keys must NOT be in the hostile (must-be-absent) set: they are
    # compared, not banned. Banning a correct, agreeing GOOGLE_CLOUD_PROJECT is the
    # bug the red-first suite already caught once.
    assertable = set( ASSERTABLE_PROJECT_OVERRIDES ) | set( ASSERTABLE_MODEL_OVERRIDES )
    assert not ( assertable & set( HOSTILE_ENV_KEYS ) ), (
        f"{sorted( assertable & set( HOSTILE_ENV_KEYS ) )} is both ASSERTABLE and HOSTILE. "
        "A guard that fires on a valid configuration teaches people to disable guards. "
        "C4 was exactly this bug, one bucket over from the project variables."
    )
