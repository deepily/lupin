"""
The canonical live slot must beat every historical sibling — row f99bed95.

MEASURED, not reasoned about. `io/mementos/` in the live repo holds 37 files
matching `rio*`: one canonical `rio.md` and 36 historical siblings. On
2026-08-29 Rio wrote a fresh memento to the canonical slot at 18:35 and his
successor's boot receipt named `rio-ea46bc1a.md` instead — a record written
2.8 days earlier — so the wake check alarmed STALE_MEMENTO against a seat that
was fine.

THE MECHANISM. `_memento_candidates` ranks by a two-tier key: tier 1 for a
record carrying a `written_at` header stamp, tier 0 for one without (mtime
fallback). Tier 1 outranks tier 0 unconditionally. A bare `<slug>.md` written
by hand frequently carries NO header, so the freshest record a seat owns is
demoted below every stamped sibling no matter how old. Against the live tree
`io/mementos/rio.md` ranked 44th of 79 candidates.

BLAST RADIUS, measured against the live tree before the fix: 13 personas hold a
canonical slot; 9 of them (arnold, cheech, chloe, clayton, krishna, rio, sam,
tiberius, tiffany) resolved to a historical sibling rather than their own slot.
The 4 that were already correct (john, maya, pocholo, rachel) are the 4 whose
slot carries a `written_at` stamp — which is the mechanism stated as a
prediction and then confirmed.

WHY THE FIXTURES ARE POPULATED. A single-file fixture cannot reproduce this:
with one candidate the ranking never runs. That is plausibly why the defect
survived a suite that already covered this resolver. Every reproduction below
plants a directory with siblings in it.

WHY THE ASSERTIONS GO THROUGH THE BOOT PATH. `_resolve_memento_path` returning
the right string is necessary and not sufficient — the defect was VISIBLE in
the boot receipt and the wake-check verdict computed from it. The end-to-end
tests here drive `_build_memento_block` (what the SessionStart hook actually
calls), read the receipt it wrote, and classify it exactly as the arbiter does.
"""
import datetime
import json
import os

import pytest

from cosa.agents.heartbeat_arbiter import respin_wake_check as rwc
from lupin_cli.claude_code.hooks.register_session import (
    _build_memento_block,
    _resolve_memento_path,
)

SID_FRESH = "ffffffff-1111-2222-3333-444444444444"

# The live specimen: the sibling both bad reports named, and the stamp it carries.
STALE_SIBLING_SID   = "ea46bc1a"
STALE_SIBLING_STAMP = "2026-08-27T02:49:00+00:00"


def _io_slot( root ):
    slot = os.path.join( root, "io", "mementos" )
    os.makedirs( slot, exist_ok=True )
    return slot


def _write( path, *, persona=None, sid8=None, written_at=None, body="held state\n" ):
    """
    Write a memento. With no persona/sid8 it is HEADERLESS — the shape the live
    canonical slots actually have (9 of 13 measured), and the shape the ranking
    demotes.
    """
    lines = []
    if persona:
        stamp = f" written_at={written_at}" if written_at else ""
        lines.append( f"<!-- memento-record: persona={persona} session_id={sid8}{stamp} slot=io -->\n" )
    lines.append( "# Memento\n" )
    lines.append( body )
    with open( path, "w", encoding="utf-8" ) as fh:
        fh.write( "".join( lines ) )
    return path


def _populate_rio( root, *, n_siblings=36, slot_body="held state\n" ):
    """
    The live directory's shape: one headerless canonical slot plus a crowd of
    stamped historical siblings, one of which is the specimen `ea46bc1a`.
    """
    slot_dir = _io_slot( root )
    for i in range( n_siblings - 1 ):
        _write( os.path.join( slot_dir, f"rio-{i:08d}.md" ),
                persona="rio", sid8=f"{i:08d}", written_at=f"2026-08-2{i % 7}T10:00:00+00:00" )
    stale = _write( os.path.join( slot_dir, f"rio-{STALE_SIBLING_SID}.md" ),
                    persona="rio", sid8=STALE_SIBLING_SID, written_at=STALE_SIBLING_STAMP )
    slot = _write( os.path.join( slot_dir, "rio.md" ), body=slot_body )
    # The slot is the NEWEST file on disk by every honest measure; only the
    # missing header hides that from the ranking.
    os.utime( stale, ( 1_000_000, 1_000_000 ) )
    return slot, stale


@pytest.fixture
def repo( tmp_path ):
    return str( tmp_path )


# ---------------------------------------------------------------------------
# The reproduction, at the resolver
# ---------------------------------------------------------------------------
def test_headerless_canonical_slot_beats_36_stamped_siblings( repo ):
    """
    THE ROW'S REPRODUCTION. Before the fix this returned `rio-ea46bc1a.md` —
    the exact file both bad reports named — because the canonical slot carries
    no `written_at` and tier 1 outranks tier 0 unconditionally.
    """
    slot, stale = _populate_rio( repo )
    resolved = _resolve_memento_path( SID_FRESH, "Rio", repo )
    assert resolved == slot
    assert resolved != stale


def test_one_stamped_sibling_is_enough_to_lose_the_slot_without_the_fix( repo ):
    """
    The minimum populated directory that reproduces it: TWO files. A one-file
    fixture cannot — with a single candidate the ranking never runs at all,
    which is why a suite that already covered this resolver stayed green.
    """
    slot_dir = _io_slot( repo )
    _write( os.path.join( slot_dir, "rio-ea46bc1a.md" ),
            persona="rio", sid8="ea46bc1a", written_at=STALE_SIBLING_STAMP )
    slot = _write( os.path.join( slot_dir, "rio.md" ) )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) == slot


def test_a_single_file_directory_cannot_reproduce_it( repo ):
    """
    NEGATIVE CONTROL for the sentence above. With only the slot present the old
    code and the new code agree — so a green here proves nothing about the
    defect, and this test exists to say that in the suite rather than in prose.
    """
    slot = _write( os.path.join( _io_slot( repo ), "rio.md" ) )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) == slot


# ---------------------------------------------------------------------------
# Controls — what the preference must NOT do
# ---------------------------------------------------------------------------
def test_exact_session_id_still_outranks_the_canonical_slot( repo ):
    """
    Step 1 stays first. A record naming THIS seat's id is unambiguously ours —
    the strongest signal there is — and a bare slot must not displace it.
    """
    slot_dir = _io_slot( repo )
    mine = _write( os.path.join( slot_dir, "rio-ffffffff.md" ),
                   persona="rio", sid8="ffffffff", written_at="2026-08-01T00:00:00+00:00" )
    _write( os.path.join( slot_dir, "rio.md" ) )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) == mine


def test_the_slot_is_still_persona_confirmed( repo ):
    """
    A bare filename is a CLAIM. A slot whose header declares another persona is
    not this seat's state, and handing a seat somebody else's memento stays
    worse than handing it none.
    """
    slot_dir = _io_slot( repo )
    _write( os.path.join( slot_dir, "rio.md" ), persona="arnold", sid8="ca8fbfcc",
            written_at="2026-08-29T18:35:00+00:00" )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) is None


def test_the_mirrors_copy_of_the_bare_name_is_never_promoted( repo, tmp_path, monkeypatch ):
    """
    The mirror under ~/.claude/mementos holds a same-named `<slug>.md` whose copy
    goes stale on its own schedule — that is exactly what respin_wake_check's
    SLOT_MIRROR alarm exists to catch. Only THIS repo's slot is canonical.

    Here the repo has no slot at all, so the promotion must not fire and the
    ordinary newest-record rule must decide. If the mirror's bare name were
    promoted, the seat would rehydrate from the copy instead of the record.
    """
    home = tmp_path / "home"
    monkeypatch.setenv( "HOME", str( home ) )
    monkeypatch.setattr( os.path, "expanduser",
                         lambda p: p.replace( "~", str( home ), 1 ) if p.startswith( "~" ) else p )

    mirror_io = os.path.join( str( home ), ".claude", "mementos", os.path.basename( repo ), "io", "mementos" )
    os.makedirs( mirror_io, exist_ok=True )
    _write( os.path.join( mirror_io, "rio.md" ) )

    fresh = _write( os.path.join( _io_slot( repo ), "rio-00ee9fa9.md" ),
                    persona="rio", sid8="00ee9fa9", written_at="2026-08-29T18:35:00+00:00" )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) == fresh


def test_no_canonical_slot_leaves_the_newest_sibling_rule_intact( repo ):
    """
    NEGATIVE CONTROL. With no bare slot present the new branch must not fire and
    the pre-existing newest-by-stamp rule must still decide.
    """
    slot_dir = _io_slot( repo )
    _write( os.path.join( slot_dir, "rio-11111111.md" ),
            persona="rio", sid8="11111111", written_at="2026-08-01T00:00:00+00:00" )
    newest = _write( os.path.join( slot_dir, "rio-22222222.md" ),
                     persona="rio", sid8="22222222", written_at="2026-08-29T18:35:00+00:00" )
    assert _resolve_memento_path( SID_FRESH, "Rio", repo ) == newest


def test_an_accented_persona_still_finds_its_folded_slot( repo ):
    """
    "María" slugs naively to `mar-a`; writers produce `maria.md`. The slot
    preference walks the same slug list the rest of the resolver does, so the
    fold must survive the new branch.
    """
    slot_dir = _io_slot( repo )
    _write( os.path.join( slot_dir, "maria-99999999.md" ),
            persona="maria", sid8="99999999", written_at="2026-08-29T00:00:00+00:00" )
    slot = _write( os.path.join( slot_dir, "maria.md" ) )
    assert _resolve_memento_path( SID_FRESH, "María", repo ) == slot


# ---------------------------------------------------------------------------
# End-to-end — what the RUN produces, not what the function returns
# ---------------------------------------------------------------------------
def _boot_and_read_receipt( repo, tmp_path, monkeypatch, persona="Rio", sid=SID_FRESH ):
    """
    Drive the real boot path and hand back the receipt it wrote.

    `_resolve_base_dir` is redirected so a unit run cannot plant a live-looking
    receipt in the fleet's real data root — the false green measured 2026-08-23.
    """
    out = tmp_path / "receipts"
    out.mkdir()
    monkeypatch.setattr( rwc, "_resolve_base_dir", lambda base_dir: str( out ) )
    block = _build_memento_block( sid, persona, repo_root=repo )
    receipt = rwc.read_receipt( str( out ), sid )
    return block, receipt


def test_the_boot_receipt_names_the_canonical_slot_not_the_stale_sibling( repo, tmp_path, monkeypatch ):
    """
    THE ARTIFACT THE DEFECT WAS VISIBLE IN. The wake check does not resolve
    anything itself — it reads `memento_path` out of this receipt. On 2026-08-29
    that field named `io/mementos/rio-ea46bc1a.md`.
    """
    slot, stale = _populate_rio( repo )
    _, receipt = _boot_and_read_receipt( repo, tmp_path, monkeypatch )

    assert receipt is not None
    assert receipt[ "memento_path" ] == slot
    assert os.path.basename( receipt[ "memento_path" ] ) != f"rio-{STALE_SIBLING_SID}.md"
    assert receipt[ "memento_slot" ] == rwc.SLOT_REPO_IO


def test_the_wake_check_no_longer_alarms_stale_on_a_seat_that_is_fine( repo, tmp_path, monkeypatch ):
    """
    THE VERDICT THE ROW WAS FILED ON, computed the way the arbiter computes it.
    The stale sibling's stamp is 2.8 days old against a 3600s limit, so before
    the fix this receipt classified STALE_MEMENTO and the seat read as broken.

    The canonical slot is headerless, so it carries no `written_at` to age — and
    an absent stamp must not be treated as an old one. RETURNED is the honest
    verdict: it woke, and it consumed the live record.
    """
    _populate_rio( repo )
    _, receipt = _boot_and_read_receipt( repo, tmp_path, monkeypatch )

    fired = datetime.datetime.fromisoformat( receipt[ "booted_at" ] ) - datetime.timedelta( seconds=30 )
    verdict = rwc.classify_wake( receipt, fired_at=fired,
                                 now=datetime.datetime.now( datetime.timezone.utc ) )
    assert verdict.verdict == rwc.WakeVerdict.RETURNED
    assert verdict.is_alarm is False


def test_the_stale_sibling_really_would_have_alarmed( repo, tmp_path, monkeypatch ):
    """
    POSITIVE CONTROL for the test above. A green there means nothing unless the
    OTHER file genuinely trips the alarm — otherwise the assertion could pass on
    a wake check that alarms at nothing. Same receipt shape, sibling path.
    """
    _, stale = _populate_rio( repo )
    _, receipt = _boot_and_read_receipt( repo, tmp_path, monkeypatch )

    receipt[ "memento_path" ]       = stale
    receipt[ "memento_written_at" ] = STALE_SIBLING_STAMP
    fired = datetime.datetime.fromisoformat( receipt[ "booted_at" ] ) - datetime.timedelta( seconds=30 )
    verdict = rwc.classify_wake( receipt, fired_at=fired,
                                 now=datetime.datetime.now( datetime.timezone.utc ) )
    assert verdict.verdict == rwc.WakeVerdict.STALE_MEMENTO
    assert verdict.is_alarm is True


def test_the_seat_is_handed_the_fresh_bytes_not_the_stale_ones( repo, tmp_path, monkeypatch ):
    """
    The end the whole chain exists for: what the SESSION reads at boot. The
    receipt is a diagnostic; this is the state the successor actually rehydrates
    from, and it is the thing a wrong resolution silently corrupts.
    """
    _populate_rio( repo, slot_body="BOARD IS EMPTY — five rows closed this cycle\n" )
    block, _ = _boot_and_read_receipt( repo, tmp_path, monkeypatch )
    assert "rio.md" in block
    assert f"rio-{STALE_SIBLING_SID}.md" not in block
