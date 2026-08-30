"""
No source file in this tree is currently shadowed by stale cached bytecode — and the detector that
says so is itself proven able to see the condition.

Row `d18ce9ef`. CPython validates a `.pyc` on the source's **whole-second** mtime plus its **size**,
so an edit changing neither is invisible and the stale bytecode is served as valid. Measured twice
on 2026-08-29 without anyone hunting for it: on `src/cosa/rest/job_state.py` during the AC-G4
mutation sweep, and on `tests/helpers/pyc_freshness.py` while the helper was being written.

WHY A DOC WAS NOT ENOUGH, stated because the docs landed first (`4b5426da`) and this file is not a
duplicate of them. CLAUDE.md's own heartbeat-hold note records a correctly-worded instruction that
half the fleet broke anyway, where the remedy turned out to be a detector rather than better
wording. This is that detector.

🔴 THE FAILURE MODE THIS FILE IS BUILT AGAINST IS ITS OWN GREEN. A detector whose comparison is
broken reports zero findings forever and reads exactly like a clean tree. Two independent defenses,
both permanent:

  1. `test_the_detector_actually_sees_a_shadowing_pyc` manufactures the condition in a temp dir and
     requires the detector to catch it. If the comparison ever stops working, THIS goes red — the
     tree scan cannot, because a broken comparison and a clean tree produce the same output.
  2. `test_the_scan_examined_a_meaningful_number_of_files` fails on a scan that assessed too few
     files. A scan that examined nothing is the purest vacuous pass there is, and it is exactly
     what a wrong root path or an over-eager filter produces.

⚠️ NOT HYPOTHETICAL. The first version of this detector compared `marshal.dumps` output and
reported **1093** shadowed files in `src/cosa` where the truth was **zero** — `marshal` emits
back-references, so re-dumping equal objects yields different bytes. That defect was caught only
because 1093 was implausible. The inverse defect — a comparison that never differs — produces a
*plausible* zero, and nothing but defense 1 would ever catch it.
"""

import os
import subprocess
import sys

from pathlib import Path

import pytest

REPO_ROOT = Path( __file__ ).resolve().parents[ 3 ]
if str( REPO_ROOT / "src" ) not in sys.path: sys.path.insert( 0, str( REPO_ROOT / "src" ) )

from tests.helpers.pyc_freshness import (            # noqa: E402
    bytecode_files_for,
    describe_shadowing,
    find_shadowing_bytecode,
    invalidation_mode_is_safe,
    scan_is_meaningful,
)

# WIDENED (row ae7ed041). The three original roots missed every other first-party package, and
# the drift that row measured — 77 timestamp pycs surviving on a supposedly-migrated tree — was
# CONCENTRATED IN src/lupin_mcp, which this guard never looked at. That is the third drift path
# CLAUDE.md names, "a module imported for the first time since the last conversion", and lupin_mcp
# is imported by the running MCP server rather than by the test tier, so nothing in the pyramid
# was re-converting it and nothing was watching it either. A guard whose roots exclude the code
# most likely to drift reports clean about the part of the tree it chose not to look at.
SCAN_ROOTS = [ REPO_ROOT / "src" / "cosa",
               REPO_ROOT / "src" / "tests",
               REPO_ROOT / "src" / "lupin_app",
               REPO_ROOT / "src" / "lupin_mcp",
               REPO_ROOT / "src" / "lupin_cli",
               REPO_ROOT / "src" / "lupin_arbiter_app",
               REPO_ROOT / "src" / "lupin_model_server" ]

# A scan that assesses fewer than this has not looked at the tree, whatever it returns. Set well
# below the ~2,100 observed on 2026-08-29 so ordinary growth or a pruned cache cannot make it flap;
# it exists to catch a scan that collapsed, not to pin a count.
MIN_ASSESSABLE = 200


def _manufacture_shadowed_source( tmp_path ):
    """
    Build a source file that a valid-looking `.pyc` shadows: compile one text, replace it with a
    DIFFERENT text of the SAME length, then force the source's mtime onto the pyc's whole second.
    `touch`-equivalent rather than a sleep, so it is deterministic rather than a timing gamble.
    """
    src = tmp_path / "shadowed.py"
    src.write_text( 'VALUE = "dead"\n', encoding="utf-8" )
    subprocess.run( [ sys.executable, "-c",
                      f"import sys; sys.path.insert( 0, {str( tmp_path )!r} ); import shadowed" ],
                    capture_output=True, timeout=60 )
    src.write_text( 'VALUE = "todo"\n', encoding="utf-8" )       # same length

    pycs = bytecode_files_for( src )
    assert pycs, "no .pyc was produced — this probe cannot manufacture the condition it needs"
    stat = pycs[ 0 ].stat()
    os.utime( src, ( stat.st_atime, stat.st_mtime ) )
    return src


def test_the_detector_actually_sees_a_shadowing_pyc( tmp_path ):
    """
    DEFENSE 1 — the control that makes every other green in this file mean something.

    Ensures:
        - a manufactured shadowed source is reported
        - the count of assessable files is non-zero, so the finding came from a real scan
    """
    src = _manufacture_shadowed_source( tmp_path )

    tally = find_shadowing_bytecode( [ tmp_path ] )

    assert tally.examined >= 1
    assert src in tally.shadowed, (
        "the detector did NOT see a shadowing .pyc that was deliberately manufactured. Its "
        "comparison is broken, which means its zero-findings result on the real tree is "
        "meaningless — a broken comparison and a clean tree look identical from the outside."
    )


def test_a_source_with_matching_bytecode_is_not_reported( tmp_path ):
    """
    The paired negative. Without it, a detector that flags EVERYTHING also passes defense 1, and
    the tree scan below would be the only thing objecting — from the wrong direction.

    Ensures:
        - an ordinary compiled source is not reported
    """
    src = tmp_path / "honest.py"
    src.write_text( 'VALUE = "todo"\n', encoding="utf-8" )
    subprocess.run( [ sys.executable, "-c",
                      f"import sys; sys.path.insert( 0, {str( tmp_path )!r} ); import honest" ],
                    capture_output=True, timeout=60 )

    tally = find_shadowing_bytecode( [ tmp_path ] )

    assert tally.examined >= 1
    assert tally.shadowed == []


def test_the_scan_examined_a_meaningful_number_of_files():
    """
    DEFENSE 2 — a scan that looked at nothing reports a clean tree.

    "Looked at nothing" has TWO opposite causes and they used to share one failure string
    (row 866f43ce): the checked-hash migration landed, so nothing CAN be shadowed, or the cache
    is cold, so nothing WAS read. `scan_is_meaningful` separates them; the first is a pass.

    Ensures:
        - the real scan met the floor on assessable OR on hash-protected sources
    """
    tally   = find_shadowing_bytecode( SCAN_ROOTS )
    ok, why = scan_is_meaningful( tally, MIN_ASSESSABLE )

    assert ok, f"{why}\nRoots scanned: {[ str( r ) for r in SCAN_ROOTS ]}"


def test_no_source_in_the_tree_is_shadowed_by_stale_bytecode():
    """
    THE ASSERTION ITSELF.

    A red here is not necessarily anyone's mistake: a peer editing a file in the same second its
    bytecode was compiled produces a genuine, transient instance. The remedy in the message is safe
    to run either way, and results touching the named files are void until it is.

    Ensures:
        - no assessable source in src/cosa, src/tests or src/lupin_app is shadowed
    """
    tally = find_shadowing_bytecode( SCAN_ROOTS )

    assert not tally.shadowed, describe_shadowing( tally.shadowed )
    # (3) the mode question — a tree that is one edit from permanent shadowing is not clean,
    # even when nothing is shadowed today.
    safe, why_safe = invalidation_mode_is_safe( tally )
    assert safe, why_safe
    # belt: a scan that looked at nothing must not read as a pass — but a MIGRATED tree looked at
    # nothing for the right reason, so this asks scan_is_meaningful rather than examined alone.
    ok, why = scan_is_meaningful( tally, MIN_ASSESSABLE )
    assert ok, why


def test_the_failure_message_names_the_files_and_the_remedy():
    """
    The remedy is only reachable by making the test fail, so nobody would ever read it — unless it
    is asserted directly. A message that omits it turns a loud failure into a puzzle.

    Ensures:
        - every offending path appears in the text
        - the cache-clear command appears, runnable as written
        - the row id is present so the reader can find the measurement
    """
    text = describe_shadowing( [ Path( "/x/alpha.py" ), Path( "/x/beta.py" ) ] )

    assert "/x/alpha.py" in text and "/x/beta.py" in text
    assert "src/scripts/purge-pycache.sh" in text
    assert "d18ce9ef" in text


def test_empty_roots_are_refused_rather_than_reported_clean():
    """
    An empty root list is the shortest path to a vacuous green, and a caller can produce one by
    accident (a filtered list, a missing directory).

    Ensures:
        - an empty roots list raises
        - a non-existent root raises rather than being skipped
    """
    with pytest.raises( AssertionError, match="no roots given" ):
        find_shadowing_bytecode( [] )

    with pytest.raises( AssertionError, match="root does not exist" ):
        find_shadowing_bytecode( [ REPO_ROOT / "no_such_directory_here" ] )


# ── The two-causes split (row 866f43ce) ───────────────────────────────────────
# `examined == 0` used to be one failure string over two opposite facts: the checked-hash
# migration landed (nothing CAN be shadowed — the goal state), or the cache is cold (nothing WAS
# read — the scan is blind). Measured on the live tree 2026-08-30: 2,158 sources hash-protected,
# ZERO timestamp-assessable, against the "~2,100 observed on 2026-08-29" this floor was set from.
# The population did not shrink; its invalidation mode flipped, and the guard called that a
# failure while naming three causes, none of which was the real one.

def _tally( examined, hash_protected, shadowed=() ):
    from tests.helpers.pyc_freshness import ScanTally
    return ScanTally( list( shadowed ), examined, hash_protected )


def test_a_migrated_tree_passes_even_though_it_assessed_nothing():
    ok, why = scan_is_meaningful( _tally( examined=0, hash_protected=2158 ), MIN_ASSESSABLE )

    assert ok
    assert "MIGRATION HAVING LANDED" in why
    assert "cannot shadow" in why


def test_a_cold_cache_fails_even_though_it_also_assessed_nothing():
    ok, why = scan_is_meaningful( _tally( examined=0, hash_protected=0 ), MIN_ASSESSABLE )

    assert not ok
    assert "blind scan" in why


def test_the_two_zero_examined_cases_do_not_share_a_verdict_or_a_message():
    """The split itself: identical `examined`, opposite verdicts, different text."""
    migrated_ok, migrated_why = scan_is_meaningful( _tally( 0, 2158 ), MIN_ASSESSABLE )
    cold_ok,     cold_why     = scan_is_meaningful( _tally( 0, 0 ),    MIN_ASSESSABLE )

    assert migrated_ok is True and cold_ok is False
    assert migrated_why != cold_why


def test_an_assessable_tree_still_passes_the_old_way():
    ok, why = scan_is_meaningful( _tally( examined=2100, hash_protected=0 ), MIN_ASSESSABLE )

    assert ok and "is evidence" in why


def test_every_verdict_names_both_counts_so_it_can_be_re_derived():
    for tally in ( _tally( 0, 2158 ), _tally( 0, 0 ), _tally( 2100, 0 ), _tally( 5, 5 ) ):
        _ok, why = scan_is_meaningful( tally, MIN_ASSESSABLE )
        assert f"{tally.examined} assessable"      in why
        assert f"{tally.hash_protected} protected" in why


def test_the_cold_cache_remedy_does_not_tell_you_to_reintroduce_the_defect():
    """
    A remedy that says "run a suite to warm the cache" would clear the message by writing
    TIMESTAMP pycs — CPython's default, and the exact invalidation mode 866f43ce moved off.
    The remedy must name the migration script instead. (I wrote the wrong one first.)
    """
    _ok, why = scan_is_meaningful( _tally( 0, 0 ), MIN_ASSESSABLE )

    assert "migrate-pyc-to-checked-hash.sh" in why
    # assert the HAZARD is named, not one phrasing of it — this file already carried one test
    # that went red because 65a55eb2 reworded the message under a literal assertion, and the
    # first version of THIS test repeated the mistake within the hour.
    assert "WARMING THE CACHE" in why and "TIMESTAMP" in why


def test_hash_protected_sources_are_counted_and_not_assessed( tmp_path ):
    """
    End to end on real bytecode: a source compiled with checked-hash invalidation must land in
    `hash_protected`, never in `examined` — it is not a gap in the scan, it is immune by
    construction.
    """
    import py_compile
    src = tmp_path / "hashed.py"
    src.write_text( "VALUE = 1\n", encoding="utf-8" )
    py_compile.compile( str( src ), doraise=True,
                        invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH )

    tally = find_shadowing_bytecode( [ tmp_path ] )

    assert tally.hash_protected == 1
    assert tally.examined == 0
    assert tally.shadowed == []


def test_timestamp_sources_are_assessed_not_counted_as_protected( tmp_path ):
    """The other arm, so the two counters cannot both be fed by one branch."""
    import py_compile
    src = tmp_path / "stamped.py"
    src.write_text( "VALUE = 1\n", encoding="utf-8" )
    py_compile.compile( str( src ), doraise=True,
                        invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP )

    tally = find_shadowing_bytecode( [ tmp_path ] )

    assert tally.examined == 1
    assert tally.hash_protected == 0


def test_the_tally_is_addressed_by_FIELD_not_by_position( tmp_path ):
    """
    An earlier version of this test asserted three-value unpacking, and adding the
    `unchecked` field broke it within the hour. Positional unpacking is a promise that
    expires the next time the tally learns something; the field names are the contract.
    """
    ( tmp_path / "x.py" ).write_text( "V = 1\n", encoding="utf-8" )
    tally = find_shadowing_bytecode( [ tmp_path ] )

    assert tally.shadowed == [] and tally.examined == 0
    assert tally.hash_protected == 0 and tally.unchecked == 0


def test_the_remedy_names_the_raw_purge_as_a_way_to_revert_the_tree():
    """
    A raw `rm -rf __pycache__` deletes every checked-hash pyc, and what gets compiled next is
    TIMESTAMP-based — a deleted file carries no mode to inherit, and timestamp is CPython's
    default. So the most obvious "clear the cache" reflex REVERTS the tree into the invalidation
    mode row 866f43ce moved off, and the message has to say so or it is inviting the reflex.
    """
    _ok, why = scan_is_meaningful( _tally( 0, 0 ), MIN_ASSESSABLE )

    assert "RAW PURGE" in why
    assert "purge-pycache.sh" in why
    assert "RECONVERT" in why


def test_the_scan_covers_every_first_party_package_not_just_three():
    """
    ROW ae7ed041's other half. The drift it measured — timestamp pycs surviving a migration —
    was concentrated in src/lupin_mcp, which the original three roots did not include. A guard
    that reports clean about the code it declined to look at is the vacuous pass this file exists
    to prevent, one level up from the count.
    """
    scanned = { root.name for root in SCAN_ROOTS }

    for package in ( "cosa", "tests", "lupin_app", "lupin_mcp",
                     "lupin_cli", "lupin_arbiter_app", "lupin_model_server" ):
        assert package in scanned, f"{package} is first-party source and is not scanned"


def test_every_scan_root_exists_so_a_typo_cannot_silently_shrink_the_scan():
    """A root that does not exist raises in find_shadowing_bytecode — assert it here too, so a
    renamed package is a named failure rather than a quietly smaller denominator."""
    for root in SCAN_ROOTS:
        assert root.is_dir(), f"scan root does not exist: {root}"


# ── The THIRD invalidation mode (Tiberius 👑, reviewing 18593313) ─────────────
# CPython has three, not two: bit 0 is hash-based, bit 1 is check_source.
#   TIMESTAMP flags=0 · CHECKED_HASH flags=3 · UNCHECKED_HASH flags=1
# Testing `flags & 1` alone reads UNCHECKED-hash as protected — exactly backwards, because
# CPython never revalidates it. Measured: a module compiled UNCHECKED_HASH kept serving the OLD
# value after its source was rewritten; the same edit under CHECKED_HASH served the new one.

def _compile_as( tmp_path, name, mode, text="VALUE = 1\n" ):
    import py_compile
    src = tmp_path / f"{name}.py"
    src.write_text( text, encoding="utf-8" )
    py_compile.compile( str( src ), doraise=True,
                        invalidation_mode=getattr( py_compile.PycInvalidationMode, mode ) )
    return src


def test_the_three_modes_are_told_apart( tmp_path ):
    from tests.helpers.pyc_freshness import (
        pyc_invalidation_mode, MODE_TIMESTAMP, MODE_CHECKED_HASH, MODE_UNCHECKED_HASH )

    assert pyc_invalidation_mode( _compile_as( tmp_path, "a", "TIMESTAMP"      ) ) == MODE_TIMESTAMP
    assert pyc_invalidation_mode( _compile_as( tmp_path, "b", "CHECKED_HASH"   ) ) == MODE_CHECKED_HASH
    assert pyc_invalidation_mode( _compile_as( tmp_path, "c", "UNCHECKED_HASH" ) ) == MODE_UNCHECKED_HASH
    assert pyc_invalidation_mode( tmp_path / "never_compiled.py" ) is None


def test_an_unchecked_hash_pyc_is_NOT_counted_as_protected( tmp_path ):
    """The defect itself. `flags & 1` is true for BOTH hash modes; only checked-hash is safe."""
    _compile_as( tmp_path, "unchecked", "UNCHECKED_HASH" )

    tally = find_shadowing_bytecode( [ tmp_path ] )

    assert tally.hash_protected == 0, "an unchecked-hash pyc was counted as protected"
    assert tally.unchecked == 1


def test_one_unchecked_hash_pyc_makes_the_mode_unsafe_at_any_count():
    """
    THE THIRD QUESTION, and it belongs to its own predicate (Tiberius). No floor rescues it: a
    tree with 2,158 genuinely-protected sources AND one unchecked-hash pyc is still unsafe,
    because that one file can never self-correct.
    """
    from tests.helpers.pyc_freshness import ScanTally

    ok, why = invalidation_mode_is_safe( ScanTally( [], 0, 2158, 1 ) )

    assert not ok
    assert "UNCHECKED" in why and "never revalidates" in why


def test_a_fully_migrated_tree_reports_a_safe_mode():
    from tests.helpers.pyc_freshness import ScanTally

    ok, why = invalidation_mode_is_safe( ScanTally( [], 0, 2158, 0 ) )

    assert ok and "no unchecked-hash" in why


def test_the_three_questions_are_answered_by_three_DIFFERENT_predicates():
    """
    The separation itself. An unchecked-hash pyc that currently MATCHES its source is:
      - not shadowing anything today          -> find_shadowing_bytecode says nothing
      - no obstacle to a meaningful scan      -> scan_is_meaningful can still pass
      - a tree one edit from permanent damage -> invalidation_mode_is_safe REFUSES
    Collapsing any two of these makes one of the three answers a lie.
    """
    from tests.helpers.pyc_freshness import ScanTally
    tally = ScanTally( [], 0, 2158, 1 )        # protected floor met, one unchecked pyc, none stale

    assert tally.shadowed == []                                        # (1) nothing shadowed YET
    assert scan_is_meaningful( tally, MIN_ASSESSABLE )[ 0 ] is True     # (2) verdict IS evidence
    assert invalidation_mode_is_safe( tally )[ 0 ] is False             # (3) mode is NOT safe


def test_an_unchecked_hash_pyc_that_differs_is_reported_as_shadowing( tmp_path ):
    """
    CPython will never invalidate it, so a stale unchecked-hash pyc shadows PERMANENTLY — worse
    than the timestamp case the detector was built for, which at least clears on a size change.
    """
    src = _compile_as( tmp_path, "drifted", "UNCHECKED_HASH", "VALUE = 1\n" )
    src.write_text( "VALUE = 22222\n", encoding="utf-8" )      # size differs; nothing revalidates

    tally = find_shadowing_bytecode( [ tmp_path ] )

    assert src in tally.shadowed


def test_a_checked_hash_pyc_that_differs_is_NOT_shadowing( tmp_path ):
    """The other arm: CPython hashes the source, so a drifted checked-hash pyc is caught by it."""
    src = _compile_as( tmp_path, "safe", "CHECKED_HASH", "VALUE = 1\n" )
    src.write_text( "VALUE = 22222\n", encoding="utf-8" )

    tally = find_shadowing_bytecode( [ tmp_path ] )

    assert tally.shadowed == []
    assert tally.hash_protected == 1


def test_a_hash_based_pycs_bytes_8_to_16_are_the_source_hash_not_mtime_and_size():
    """
    WHY THE mtime GATE IS SKIPPED, and it is stronger than "the gate does not apply" (Tiberius,
    reviewing the three-mode fix). In a hash-based pyc those bytes ARE the 8-byte source hash.
    Running the timestamp gate on them would compare the source's real mtime against a slice of
    a hash — a verdict on noise, not a conservative extra check.
    """
    import importlib.util, py_compile, struct, tempfile
    from pathlib import Path

    tmp = Path( tempfile.mkdtemp() )
    src = tmp / "hashed.py"
    src.write_text( "VALUE = 1\n", encoding="utf-8" )
    py_compile.compile( str( src ), doraise=True,
                        invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH )

    raw = Path( importlib.util.cache_from_source( str( src ) ) ).read_bytes()

    assert raw[ 8:16 ] == importlib.util.source_hash( src.read_bytes() )
    # and read as (mtime, size) the same bytes are nonsense — not merely a different number
    fake_mtime, fake_size = struct.unpack( "<II", raw[ 8:16 ] )
    assert fake_mtime != int( src.stat().st_mtime )
    assert fake_size  != src.stat().st_size
