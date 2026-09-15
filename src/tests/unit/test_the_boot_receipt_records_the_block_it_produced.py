"""
The boot receipt records what the boot path PRODUCED, not only what it opened.

THE GAP THIS CLOSES. Every pre-existing field on the receipt describes the
memento FILE — which file was opened, when it was written, whose it is. None of
them describes the BLOCK, and the block is the only thing a session ever sees.
So three outcomes shared one silence:

    (1) resolved, block produced, DELIVERED       — the healthy case
    (2) resolved, block produced, LOST in transit — between the hook's
                                                    additionalContext and the
                                                    session
    (3) resolved, block came back EMPTY           — producer-side

`block_bytes` / `block_sha256` / `block_headline` split (3) from (1)+(2). They
do NOT prove delivery, and no test here claims they do — nothing written at the
producing end can. Phase 2 (an echo from the far end) narrows (1) vs (2) to
"not received OR received-and-ignored", which is smaller than today's ambiguity
and is still not zero.

WHY IT HAD TO BE BUILT BEFORE THE NEXT OCCURRENCE. A defect that destroys its
own evidence generates no pressure to instrument: every instance is already
unfixable by the time anyone looks. The boot that motivated this passed at
2026-09-05 21:30:03 and recorded nothing, so it is unmeasurable retrospectively
and always will be. The instrument is for the next one.
"""
import hashlib
import json

import pytest

from cosa.agents.heartbeat_arbiter import respin_wake_check as rwc
from lupin_cli.claude_code.hooks import register_session as rs


HEADER = "<!-- memento-record: session_id=aaaaaaaa persona=maya written_at=2026-08-21T21:00:00+00:00 -->"
SID    = "aaaaaaaa-1111-2222-3333-444444444444"


@pytest.fixture
def receipts( tmp_path, monkeypatch ):
    """
    Redirect receipt writes into a temp dir.

    🔴 NOT OPTIONAL. `_build_memento_block` stamps a LIVE receipt into the
    directory the wake check reads; a green run of the sibling suite once
    planted four real ones there, one carrying a real persona and a booted_at
    of that second. A healthy-looking receipt written by a test is a false green
    waiting to happen.
    """
    out = tmp_path / "fleet"
    out.mkdir()
    monkeypatch.setattr( rwc, "_resolve_base_dir", lambda base_dir: str( out ) )
    return out


def _memento( repo, sid8="aaaaaaaa", persona="maya", amendment=True ):
    path = repo / f".claude-memento-{persona}-{sid8}.md"
    tail = "\n<!-- memento-amendment: 1 -->\nheld merge\n" if amendment else "\n"
    path.write_text( f"{HEADER}\n\n# body\n{tail}" )
    return path


def _receipt( receipts, sid=SID ):
    return json.loads( ( receipts / f"{rwc.RECEIPT_PREFIX}{sid}.json" ).read_text() )


# ── describe_block, the one decider ─────────────────────────────────────────

def test_block_bytes_counts_utf8_bytes_and_not_characters():
    """
    The one measurement that has already been got wrong on this work: a length
    published as `len(str)` where the object is bytes. Every headline this block
    carries leads with an emoji, so the two numbers ALWAYS differ here — a
    fixture of plain ASCII would let a characters implementation pass.
    """
    block = "\n════\n  🧠  YOU HAVE A MEMENTO\n════\n"

    assert len( block )                    == 35    # characters
    assert len( block.encode( "utf-8" ) )  == 54    # bytes — the rules are 3 each, the emoji 4
    assert rwc.describe_block( block )[ "block_bytes" ] == 54


def test_the_headline_is_found_by_a_predicate_and_not_by_its_position():
    """
    Taking line index 2 is an enumeration in hiding: it encodes today's
    rule-then-headline layout. Move the headline down and a positional
    implementation returns a rule; the predicate still returns the headline.
    """
    shifted = "\n\n════\n════\n  🧠  YOU HAVE A MEMENTO\n════\n"

    assert shifted.splitlines()[ 2 ] == "════"      # what a positional read gets
    assert rwc.describe_block( shifted )[ "block_headline" ] == "🧠  YOU HAVE A MEMENTO"


def test_a_produced_empty_block_is_not_the_same_fact_as_no_block_at_all():
    """
    🔴 CLAYTON 😎's FINDING, 2026-09-06, and it is the ROOT CAUSE of a blindness
    I had already reported as a limit without knowing why.

    ⚠️ CREDIT CORRECTED 2026-09-06 01:30. The commit that added this test,
    `32929647`, opens "MARÍA'S FINDING". That is wrong: she RELAYED it, he FOUND
    it, with the receipt in hand — 0 bytes, sha e3b0c442, register_session.py.
    She raised the correction herself, unprompted, against her own credit. The
    commit message stands as history; this is the artifact carrying the fix.

    `describe_block(None)` and `describe_block("")` used to be byte-identical —
    0 bytes, the same digest, no headline. But they are different facts: `None`
    means NO BLOCK WAS SUPPLIED (an old caller, or a wiring that dropped it),
    while `""` means a block was PRODUCED and came back empty, which is state
    (3) and the one thing phase 1 exists to name.

    Collapsing them is exactly why the state-3 test could not see the unwiring
    arm: unwiring passes None, the conflation rendered it as 0, and 0 is what
    the state-3 test asserts. The instrument agreed with a broken wiring.

    An earlier version of this test asserted the empty case was
    "measured-and-empty in a way a null cannot" — while looping over BOTH inputs
    and asserting they were the same. The docstring claimed the discrimination
    the body disproved.
    """
    supplied = rwc.describe_block( "" )
    assert supplied[ "block_bytes" ]    == 0
    assert supplied[ "block_sha256" ]   == hashlib.sha256( b"" ).hexdigest()
    assert supplied[ "block_headline" ] is None

    absent = rwc.describe_block( None )
    assert absent[ "block_bytes" ]    is None      # NOT MEASURED, not zero
    assert absent[ "block_sha256" ]   is None
    assert absent[ "block_headline" ] is None

    assert supplied != absent


# ── the receipt the boot path actually writes ───────────────────────────────

def test_the_receipt_measures_the_very_block_the_boot_path_returned( tmp_path, receipts, monkeypatch ):
    """
    Producer and receipt must not be able to drift: the digest is recomputed
    here from the returned block rather than pinned to a literal, so a receipt
    describing some OTHER string fails even when both are individually valid.
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"; repo.mkdir()
    _memento( repo )

    block = rs._build_memento_block( SID, "maya", repo_root=str( repo ) )
    body  = _receipt( receipts )

    assert block                                                          # the healthy case
    assert body[ "block_bytes" ]  == len( block.encode( "utf-8" ) )
    assert body[ "block_sha256" ] == hashlib.sha256( block.encode( "utf-8" ) ).hexdigest()
    assert "YOU HAVE A MEMENTO" in body[ "block_headline" ]


def test_a_boot_that_resolved_nothing_records_zero_bytes_rather_than_staying_silent( tmp_path, receipts, monkeypatch ):
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"; repo.mkdir()                                # no memento in it

    assert rs._build_memento_block( "bbbb-2222", "maya", repo_root=str( repo ) ) == ""
    body = _receipt( receipts, "bbbb-2222" )

    assert body[ "memento_path" ]    is None
    assert body[ "block_bytes" ]     == 0
    assert body[ "block_headline" ]  is None


def test_a_resolved_memento_whose_block_came_back_empty_is_now_distinguishable( tmp_path, receipts, monkeypatch ):
    """
    🔴 THE WHOLE POINT OF THE INSTRUMENT, in one row. State (3) — the file
    resolved, and the block came back empty anyway — used to look exactly like
    the healthy case in the receipt, because the receipt only ever described the
    file. Now `memento_path` is set AND `block_bytes` is 0, and the pair says
    producer-side.
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo    = tmp_path / "repo"; repo.mkdir()
    memento = _memento( repo )

    # ⚠️ NOT by breaking `builtins.open`. The stamp now runs AFTER the render, so
    # a global break takes the receipt WRITE down too and the test measures its
    # own fixture instead of the code. Make the one FILE unreadable instead.
    memento.chmod( 0o000 )
    try:
        block = rs._build_memento_block( SID, "maya", repo_root=str( repo ) )
    finally:
        memento.chmod( 0o644 )

    body = _receipt( receipts )

    assert block                     == ""
    assert body[ "memento_path" ]    == str( memento )       # it DID resolve
    assert body[ "block_bytes" ]     == 0                    # and produced nothing
    assert body[ "block_headline" ]  is None


def test_the_boot_stamps_exactly_one_receipt( tmp_path, receipts, monkeypatch ):
    """
    Rendering before stamping was the change that let one write carry both the
    file and the block. Stamping twice would be worse than not stamping the
    block at all — a reader would have no way to tell which write it is looking
    at, and the second could overwrite the first with a different answer.
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"; repo.mkdir()
    _memento( repo )

    calls = []
    real  = rwc.write_boot_receipt
    monkeypatch.setattr( rwc, "write_boot_receipt",
                         lambda **kw: ( calls.append( kw ), real( **kw ) )[ 1 ] )

    rs._build_memento_block( SID, "maya", repo_root=str( repo ) )

    assert len( calls ) == 1


def test_a_render_that_raises_still_leaves_a_receipt_and_names_the_crash( tmp_path, receipts, monkeypatch ):
    """
    🔴 CLAYTON'S FINDING (`register_session.py:2445`, 2026-09-06), and it was a
    regression I introduced.

    The caller swallows any exception out of `_build_memento_block` into
    `memento_block = ""`. Moving the stamp BELOW the render — the very change
    that lets one write carry the block — meant a render that blew up left NO
    RECEIPT AT ALL, which is indistinguishable from "the hook never ran". That
    is the exact silence this receipt exists to end, so the instrument had been
    made narrower on the state it was built for.

    Measured as a controlled pair, one variable, the same probe both ways:
    stamp-first wrote the receipt, stamp-after did not.

    `block_error` is what keeps a crash from reading as a clean empty block:
    both are zero bytes, and they want different fixes.
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"; repo.mkdir()
    _memento( repo )

    def _boom( path ): raise RuntimeError( "render blew up" )
    monkeypatch.setattr( rs, "_render_memento_block", _boom )

    assert rs._build_memento_block( SID, "maya", repo_root=str( repo ) ) == ""
    body = _receipt( receipts )

    assert body[ "block_bytes" ]  == 0
    assert body[ "block_error" ]  == "RuntimeError"


@pytest.mark.parametrize( "raised, named", [ ( ValueError, "ValueError" ),
                                             ( KeyError,   "KeyError"   ) ] )
def test_the_recorded_error_is_the_one_that_was_actually_raised( tmp_path, receipts, monkeypatch,
                                                                 raised, named ):
    """
    🔴 THIS EXISTS BECAUSE MY FIRST NEGATIVE CONTROL DID NOT DISCRIMINATE.
    Wiring `block_error` to the constant "RuntimeError" SURVIVED a mutation arm:
    the clean-empty test never enters the except branch, so it can say nothing
    about what that branch writes, and the crash test happened to raise the very
    type the constant named.

    Two different exception types is the cheapest fixture that separates
    "records the error" from "records a word that looks like an error".
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"; repo.mkdir()
    _memento( repo )

    def _boom( path ): raise raised( "render blew up" )
    monkeypatch.setattr( rs, "_render_memento_block", _boom )

    rs._build_memento_block( SID, "maya", repo_root=str( repo ) )

    assert _receipt( receipts )[ "block_error" ] == named


def test_a_clean_empty_block_is_not_reported_as_a_crash( tmp_path, receipts, monkeypatch ):
    """
    The negative control for the test above. Without it, a `block_error` wired
    to a constant would pass — and the whole point of the field is that it
    DISTINGUISHES the crash from the ordinary empty case.
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"; repo.mkdir()                                # no memento

    assert rs._build_memento_block( "cccc-3333", "maya", repo_root=str( repo ) ) == ""
    body = _receipt( receipts, "cccc-3333" )

    assert body[ "block_bytes" ] == 0
    assert body[ "block_error" ] is None


# ── the stamp must survive EVERY step, not just the render ──────────────────

@pytest.mark.parametrize( "step", [ "_resolve_memento_path", "_header_of",
                                    "_written_at_of", "_persona_of",
                                    "_render_memento_block" ] )
def test_no_step_can_skip_the_stamp( tmp_path, receipts, monkeypatch, step ):
    """
    🔴 CLAYTON'S SECOND FINDING: the first fix wrapped the RENDER and left FOUR
    other steps able to escape before the write.

    `_written_at_of( header )` and `_persona_of( path, header )` were ARGUMENT
    EXPRESSIONS to the stamp call, so they evaluated before it and outside the
    try; `_header_of` and `_resolve_memento_path` ran earlier still. In all four
    the builder raised, the caller swallowed it to "", and NO RECEIPT FILE
    EXISTED — which is indistinguishable from "the hook never ran".

    Measured before the fix, one variable each: render OK, the other four ABSENT.
    So the instrument was reproducing its own target defect on four paths.

    Parametrized over all five rather than the four that were broken: a test
    naming only the broken ones cannot notice a sixth step being added outside
    the try later.
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"; repo.mkdir()
    _memento( repo )

    def _boom( *a, **k ): raise ValueError( "step blew up" )
    monkeypatch.setattr( rs, step, _boom )

    rs._build_memento_block( SID, "maya", repo_root=str( repo ) )

    body = _receipt( receipts )                       # the assertion IS that this exists
    assert body[ "block_bytes" ] == 0
    assert body[ "block_error" ] == "ValueError"


def test_the_recorded_fault_is_the_real_one_and_not_an_unbound_local( tmp_path, receipts, monkeypatch ):
    """
    🔴 THE TRAP CLAYTON PREDICTED BEFORE I WROTE THE FIX, and the reason every
    name is pre-initialised above the try.

    A name bound inside the try is unbound in the finally when the try failed
    before the binding, so a naive finally raises UnboundLocalError — and that
    REPLACES the original exception. The receipt would then record a variable
    name instead of the real fault, sending the next reader into innocent code.

    Failing at the FIRST step is what discriminates: it is the only case where
    nothing downstream has been bound yet, so a missing pre-initialisation shows
    up here and nowhere else.
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"; repo.mkdir()
    _memento( repo )

    def _boom( *a, **k ): raise KeyError( "the real fault" )
    monkeypatch.setattr( rs, "_resolve_memento_path", _boom )

    rs._build_memento_block( SID, "maya", repo_root=str( repo ) )

    body = _receipt( receipts )
    assert body[ "block_error" ] == "KeyError"          # not "UnboundLocalError"
    assert body[ "memento_path" ] is None               # pre-initialised, not absent


def test_even_a_baseexception_cannot_skip_the_stamp( tmp_path, receipts, monkeypatch ):
    """
    WHAT THE `finally` ACTUALLY BUYS, and it is narrower than it looks.

    An arm that replaced the `finally` with a plain stamp after the try SURVIVED
    the whole suite — correctly, because `except Exception` already guarantees
    execution falls through to it. Under `Exception` the two forms are
    equivalent, and reporting that arm as a weak test would have been wrong.

    The difference is BaseException — SystemExit, KeyboardInterrupt — which
    `except Exception` does not catch and which therefore skips a post-try
    stamp and not a `finally`. That is the whole of the gain, so this is the
    test that makes the `finally` load-bearing rather than decorative.
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )
    repo = tmp_path / "repo"; repo.mkdir()
    _memento( repo )

    def _exit( *a, **k ): raise SystemExit( "torn down mid-boot" )
    monkeypatch.setattr( rs, "_render_memento_block", _exit )

    with pytest.raises( SystemExit ):                 # it propagates, as it must
        rs._build_memento_block( SID, "maya", repo_root=str( repo ) )

    body = _receipt( receipts )                       # ...and the receipt still landed
    assert body[ "memento_path" ] is not None
    assert body[ "block_error" ]  is None             # not an Exception, so nothing named it


def test_a_repo_root_that_cannot_be_resolved_still_leaves_a_receipt( tmp_path, receipts, monkeypatch ):
    """
    🔴 THIS TEST REPLACES ONE THAT PINNED A TRADE BUILT ON A FALSE PREMISE.

    I had left `_resolve_repo_root` outside the try and written a test asserting
    it PROPAGATES, on the reasoning that wiring it in risked a receipt landing in
    the ambient repo's fleet directory. Clayton 😎 rejected that and was right:
    `_resolve_repo_root` does not raise. It settles for LUPIN_ROOT, then cwd, and
    prints a warning — so the misplaced receipt ALREADY HAPPENS on the success
    path, and keeping the call outside the try prevented nothing at all.

    Moving it in costs nothing either: if it ever did raise, repo_root stays None
    and `fleet_data_root( None )` resolves to the SAME ambient directory the
    settle would have chosen.

    ⚠️ The SETTLE itself — a non-lupin seat's receipt written into lupin's fleet
    directory — is a separate and larger finding and is NOT closed by this test.
    """
    monkeypatch.setenv( "HOME", str( tmp_path / "home" ) )

    def _boom( cwd ): raise RuntimeError( "cannot resolve the repo" )
    monkeypatch.setattr( rs, "_resolve_repo_root", _boom )

    assert rs._build_memento_block( SID, "maya", cwd=str( tmp_path ) ) == ""

    body = _receipt( receipts )                       # the assertion IS that it exists
    assert body[ "block_error" ]  == "RuntimeError"
    assert body[ "memento_path" ] is None
