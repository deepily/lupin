"""
Guard: a refusal keys on ABSENCE FROM THE COMMITTER'S OWN SECTION, never on
presence in somebody else's — and `**Status**` is not read at all.

WHY THIS EXISTS. Two seats reached the same wrong model of this guard twice in
one evening, 2026-09-01, and wrote it into four `.claude-session.md` section
notes before either of us ran it:

    "a live claim on CLAUDE.md from a dead session refuses other seats'
     legitimate commits"                                           <- FALSE
    "Krishna is still exposed on notifications.html"               <- FALSE

Both readings treat `others` as if it gates commits. It does not. `others` is
consulted ONLY to NAME an apparent owner inside a refusal that `mine` has
already decided, so it can change the WORDING of a denial and never its verdict.

MEASURED at the time, against the live manifest: a path claimed by a stale
section denied identically to a path claimed by nobody, and the seat everyone
believed was blocked was ALLOWED because the file sat in his own section.

⇒ THE CONSEQUENCE THAT MATTERS. Marking a dead section `stale` fixes nothing
mechanical — `commit_scope_guard` contains no read of `status` / `active` /
`stale` anywhere. It is a legibility fix for humans reading the file, and this
fleet's own line is that legibility and control are not the same thing.

⇒ AND WHY THIS IS A TEST RATHER THAN A PARAGRAPH. We had the prose: the module
docstring already described the stale-section residual, and both of us wrote our
reasons without reading it. A rule that depends on remembering is not installed.
These assertions fail if the semantics ever drift.

Synthetic manifests throughout — the live `.claude-session.md` is gitignored and
rewritten constantly, so a test reading it would measure whoever committed last.
"""
from lupin_cli.claude_code.hooks.lib.commit_scope_guard import (
    evaluate_commit_scope, _claims_for_session,
)

MINE    = "aaaaaaaa"
DEAD    = "bbbbbbbb"
MY_FILE = "src/mine/owned.py"
CONTESTED = "src/contested/file.py"
UNCLAIMED = "src/nobody/claims_this.py"


def _manifest( dead_status="stale" ):
    """
    Ensures:
        - returns a two-section manifest where DEAD claims CONTESTED and MINE
          claims MY_FILE, with DEAD's status caller-controlled
    """
    return (
        f"## Session: {MINE}\n"
        f"**Status**: active\n"
        f"### Touched Files\n"
        f"- 2026-09-01T19:00:00 | {MY_FILE}\n"
        f"\n---\n\n"
        f"## Session: {DEAD}\n"
        f"**Status**: {dead_status}\n"
        f"### Touched Files\n"
        f"- 2026-08-24T19:00:00 | {CONTESTED}\n"
    )


def _verdict( tmp_path, path, manifest=None, session=MINE ):
    """
    Ensures:
        - writes `manifest` into tmp_path and returns "DENY" or "ALLOW" for a
          commit staging exactly `path`
    """
    ( tmp_path / ".claude-session.md" ).write_text( manifest or _manifest() )
    v = evaluate_commit_scope(
        "Bash", { "command": "git commit -m x" },
        session_id      = session,
        cwd             = str( tmp_path ),
        staged_reader   = lambda *a, **k: [ path ],
        modified_reader = lambda *a, **k: [ path ],
    )
    return "DENY" if v.deny_reason else "ALLOW"


def test_a_path_in_my_own_section_is_allowed( tmp_path ):
    """The control. Without this passing, every DENY below is unreadable."""
    assert _verdict( tmp_path, MY_FILE ) == "ALLOW"


def test_a_dead_sections_claim_denies_exactly_as_no_claim_does( tmp_path ):
    """
    The core semantic, and the one two seats got wrong.

    Ensures:
        - a path claimed by ANOTHER section and a path claimed by NOBODY get the
          SAME verdict, so a foreign claim cannot be what causes a refusal
    """
    contested = _verdict( tmp_path, CONTESTED )
    unclaimed = _verdict( tmp_path, UNCLAIMED )
    assert contested == unclaimed == "DENY", ( contested, unclaimed )


def test_the_foreign_claim_changes_only_the_name_in_the_message( tmp_path ):
    """
    `others` decorates; `mine` decides.

    Ensures:
        - the refusal for a foreign-claimed path names that session
        - the refusal for an unclaimed path says no session
    """
    ( tmp_path / ".claude-session.md" ).write_text( _manifest() )

    def _reason( path ):
        return evaluate_commit_scope(
            "Bash", { "command": "git commit -m x" },
            session_id      = MINE,
            cwd             = str( tmp_path ),
            staged_reader   = lambda *a, **k: [ path ],
            modified_reader = lambda *a, **k: [ path ],
        ).deny_reason

    assert DEAD in _reason( CONTESTED )
    assert DEAD not in _reason( UNCLAIMED )


def test_status_is_not_read_so_stale_and_active_are_indistinguishable( tmp_path ):
    """
    Marking a section stale is a legibility fix, not a mechanical one.

    Ensures:
        - the verdict for a foreign-claimed path is identical whether the owning
          section says `stale` or `active`
    """
    as_stale  = _verdict( tmp_path, CONTESTED, manifest=_manifest( "stale"  ) )
    as_active = _verdict( tmp_path, CONTESTED, manifest=_manifest( "active" ) )
    assert as_stale == as_active == "DENY", ( as_stale, as_active )


def test_a_section_that_claims_a_file_wins_over_every_dead_claimant( tmp_path ):
    """
    The Krishna case, reduced.

    Two dead sections claim the file and the committer claims it too. The
    committer is ALLOWED — which is why "drop the dead entry" was a remedy for a
    problem that did not exist.
    """
    manifest = (
        f"## Session: {MINE}\n**Status**: active\n### Touched Files\n"
        f"- 2026-09-01T19:00:00 | {CONTESTED}\n\n---\n\n"
        f"## Session: {DEAD}\n**Status**: stale\n### Touched Files\n"
        f"- 2026-08-24T19:00:00 | {CONTESTED}\n\n---\n\n"
        f"## Session: cccccccc\n**Status**: committed\n### Touched Files\n"
        f"- 2026-08-27T02:00:00 | {CONTESTED}\n"
    )
    assert _verdict( tmp_path, CONTESTED, manifest=manifest ) == "ALLOW"


def test_an_unregistered_session_still_fails_open( tmp_path ):
    """
    The documented fail-open must survive every assertion above.

    Ensures:
        - a session with no section gets mine=None, and is not wedged by a guard
          it never adopted
    """
    ( tmp_path / ".claude-session.md" ).write_text( _manifest() )
    mine, _ = _claims_for_session( "dddddddd", cwd=str( tmp_path ) )
    assert mine is None
    assert _verdict( tmp_path, CONTESTED, session="dddddddd" ) == "ALLOW"


# ---------------------------------------------------------------------------
# The id shape every real session has, and no case above used.
# ---------------------------------------------------------------------------

MY_FULL_SESSION = f"{MINE}-3aaa-430d-a53f-f88385ee00cf"


def test_a_full_session_uuid_still_owns_its_EIGHT_CHAR_sections_claims( tmp_path ):
    """
    Every case above passes `MINE` — an id byte-identical to the manifest heading.
    A REAL session never does: `get_session_info()` hands out a full UUID and the
    manifest heading carries its first eight characters, so the live comparison is
    always the ASYMMETRIC one, `session_id.startswith( sid )`.

    🔴 THE FIXTURES SAT EXACTLY ON THE BOUNDARY THEY WERE TESTING. With equal ids
    `session_id.startswith( sid )` and `sid.startswith( session_id )` are BOTH true,
    so `or` and `and` are indistinguishable and the suite cannot tell them apart.

    Measured 2026-09-01 with `or` mutated to `and` in the foreign-claim loop:

        exact 8-char id   others = { theirs: bbbbbbbb }                unchanged
        FULL UUID         others = { theirs: bbbbbbbb, MINE: aaaaaaaa } own file, foreign
        the whole file                                                 6 passed. BLIND.

    Under that mutation a session's OWN file is reported as claimed by another
    section — a false refusal on every commit the fleet makes. This case is the one
    that sees it: it fails on the mutant and passes on the real code.

    Asserted on `_claims_for_session` directly rather than through a verdict, because
    the verdict collapses both halves into one word and the split between `mine` and
    `others` is the thing under test.
    """
    ( tmp_path / ".claude-session.md" ).write_text( _manifest() )

    mine, others = _claims_for_session( MY_FULL_SESSION, cwd=str( tmp_path ) )

    assert MY_FULL_SESSION != MINE, (
        "this case must use an id LONGER than the heading, or it repeats the cases above"
    )
    assert mine == { MY_FILE }, f"a full uuid did not claim its own section: {mine}"
    assert MY_FILE not in others, (
        f"the session\'s OWN file is reported as claimed by {others.get( MY_FILE )!r} — "
        f"a foreign-claim refusal on the committer\'s own work"
    )
    assert others == { CONTESTED : DEAD }
