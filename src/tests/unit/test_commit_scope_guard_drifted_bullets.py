"""
Row 22957fe9 — the commit-scope guard reads the manifest the fleet actually writes, and
says so when it cannot.

THE REPORT (María 🌸, 2026-09-17). The guard refused her commit three times with
"claimed by no session" for a file her own section listed as `- \`path\``. The documented
entry is `- <timestamp> | <path>` and the parser is faithful to it; the manifests drifted.
Measured 2026-09-18 across the lupin and planning-is-prompting manifests: 24 sections, 6
that matched and claimed NOTHING, and 1 whose heading carried a note after the id
(`## Session: d54262de (Mr. Radio 🦉 — …)`) and so did not match at all.

⚠️ THOSE TWO FAILURES POINT IN OPPOSITE DIRECTIONS, and the tests below keep them apart:

  · a section that matched and claims nothing REFUSES every file — loud, but it blamed
    the file ("claimed by no session") when the cause was the section
  · a heading that did not match is NO SECTION, which is the documented fail-open: every
    commit that seat made went unreviewed, and nothing said so

REVISED DONE-MEANS (María's second amendment): (a) a matched section that parses to zero
entries is refused or warned about loudly; (b) the drifted forms may be read, but only
together with (a). The revert arms prove the widened reader still refuses a file the
section does not list.

Synthetic manifests throughout — the live manifest is rewritten constantly.
"""
from lupin_cli.claude_code.hooks.lib import commit_scope_guard as guard
from lupin_cli.claude_code.hooks.lib.commit_scope_guard import (
    READABLE_FORMS, _parse_manifest, _parse_manifest_report, evaluate_commit_scope,
)

SID       = "aaaaaaaa"
MY_FILE   = "src/mine/owned.py"
UNCLAIMED = "src/nobody/claims_this.py"


def _claims( body, sid=SID ):
    return _parse_manifest( f"## Session: {sid}\n### Touched Files\n{body}\n" )[ sid ]


def _unread( body, sid=SID ):
    return _parse_manifest_report( f"## Session: {sid}\n### Touched Files\n{body}\n" )[ 1 ][ sid ]


def _verdict( tmp_path, manifest, staged, session=SID ):
    ( tmp_path / ".claude-session.md" ).write_text( manifest )
    return evaluate_commit_scope(
        "Bash", { "command": "git commit -m x" },
        session_id    = session,
        cwd           = str( tmp_path ),
        staged_reader = lambda *a, **k: list( staged ),
    )


# ── (b) THE DRIFTED FORMS ARE READ ───────────────────────────────────────────
def test_a_backtick_bullet_claims_its_path():
    assert _claims( f"- `{MY_FILE}`" ) == { MY_FILE }


def test_a_backtick_bullet_with_a_note_claims_only_the_path():
    assert _claims( f"- `{MY_FILE}` — new, row 22957fe9" ) == { MY_FILE }


def test_a_bare_path_bullet_claims_its_path():
    assert _claims( f"- {MY_FILE}" ) == { MY_FILE }


def test_a_bare_path_with_a_parenthetical_or_dash_note_claims_only_the_path():
    assert _claims( f"- {MY_FILE} (committed be36ed33)" ) == { MY_FILE }
    assert _claims( f"- {MY_FILE} — same" )               == { MY_FILE }
    assert _claims( f"- {MY_FILE} -- same" )              == { MY_FILE }


def test_a_documented_entry_with_a_backticked_path_claims_the_path_not_the_backticks():
    assert _claims( f"- 2026-09-18T20:00:00 | `{MY_FILE}`" ) == { MY_FILE }


def test_the_documented_form_is_unchanged():
    assert _claims( f"- 2026-09-18T20:00:00 | {MY_FILE}" ) == { MY_FILE }
    assert _unread( f"- 2026-09-18T20:00:00 | {MY_FILE}" ) == []


# ── WHAT THE DRIFTED READER MUST NOT CLAIM ───────────────────────────────────
def test_a_prose_bullet_claims_nothing_and_is_reported():
    """`- none` and `- In flight: …` must not claim files called `none` and `In`."""
    for bullet in ( "- none", "- In flight: background agent on senderCard.ts",
                    "- COMMITTED by merge `a0ee50f`: `workflow/x.py`",
                    "- src/tests/e2e_ui/**/snapshots PNGs (rebaseline pass)" ):
        assert _claims( bullet ) == set(), bullet
        assert _unread( bullet ) == [ bullet ], bullet


def test_drifted_forms_outside_touched_files_claim_nothing():
    """Only the documented form has always been read anywhere in a section."""
    text = ( f"## Session: {SID}\n### Notes\n- `{MY_FILE}`\n- {MY_FILE}\n"
             f"- 2026-09-18T20:00:00 | src/documented.py\n" )
    claims, unread = _parse_manifest_report( text )
    assert claims[ SID ] == { "src/documented.py" }
    assert unread[ SID ] == [], "a bullet outside Touched Files is prose, not an unread claim"


def test_a_later_subheading_ends_touched_files():
    text = f"## Session: {SID}\n### Touched Files\n- `{MY_FILE}`\n### Commits\n- `abc.def`\n"
    assert _parse_manifest( text )[ SID ] == { MY_FILE }


# ── THE HEADING ──────────────────────────────────────────────────────────────
def test_a_heading_with_a_note_after_the_id_is_a_section():
    text = f"## Session: {SID} (Mr. Radio 🦉 — lupin manager)\n### Touched Files\n- `{MY_FILE}`\n"
    assert _parse_manifest( text ) == { SID: { MY_FILE } }


def test_lines_under_a_noted_heading_are_not_credited_to_the_section_above():
    """
    Measured on the live planning-is-prompting manifest: the invisible section's claims
    were credited to the seat above it, so a commit of its files by that other seat
    passed as that seat's own.
    """
    text = ( "## Session: bbbbbbbb\n### Touched Files\n- `src/b.py`\n"
             f"## Session: {SID} (note)\n### Touched Files\n- `{MY_FILE}`\n" )
    claims = _parse_manifest( text )
    assert claims[ "bbbbbbbb" ] == { "src/b.py" }
    assert claims[ SID ]        == { MY_FILE }


# ── THE GUARD, END TO END ────────────────────────────────────────────────────
def test_marias_commit_is_allowed_when_her_section_lists_it_in_backticks( tmp_path ):
    manifest = f"## Session: {SID}\n### Touched Files\n- `{MY_FILE}`\n"
    assert _verdict( tmp_path, manifest, [ MY_FILE ] ).deny_reason is None


def test_REVERT_ARM_a_backtick_section_still_refuses_a_file_it_does_not_list( tmp_path ):
    """Reading more forms must not become reading everything."""
    manifest = f"## Session: {SID}\n### Touched Files\n- `{MY_FILE}`\n"
    reason   = _verdict( tmp_path, manifest, [ MY_FILE, UNCLAIMED ] ).deny_reason
    assert reason is not None
    assert f"{UNCLAIMED}   ← claimed by no session" in reason
    assert f"{MY_FILE}   ←" not in reason


def test_REVERT_ARM_a_noted_heading_no_longer_fails_open( tmp_path ):
    """Before: no section matched, so this seat's every commit was allowed unreviewed."""
    manifest = f"## Session: {SID} (Persona — role)\n### Touched Files\n- `{MY_FILE}`\n"
    assert _verdict( tmp_path, manifest, [ UNCLAIMED ] ).deny_reason is not None


# ── (a) A MATCHED SECTION THAT CLAIMS NOTHING SAYS SO ─────────────────────────
def test_a_section_claiming_zero_paths_is_named_as_the_cause( tmp_path ):
    manifest = f"## Session: {SID}\n### Touched Files\n- see the commit log\n"
    reason   = _verdict( tmp_path, manifest, [ MY_FILE ] ).deny_reason
    assert reason is not None
    assert "CLAIMS ZERO PATHS" in reason
    assert "- see the commit log" in reason, "the unread bullet must be quoted"
    assert READABLE_FORMS in reason
    assert reason.index( "CLAIMS ZERO PATHS" ) < reason.index( "claimed by no session" ), \
        "the section is the cause, so it must be read before the file list"


def test_an_empty_section_is_named_even_with_nothing_unread( tmp_path ):
    reason = _verdict( tmp_path, f"## Session: {SID}\n### Touched Files\n", [ MY_FILE ] ).deny_reason
    assert "CLAIMS ZERO PATHS" in reason
    assert "in no form" not in reason


def test_a_partly_read_section_names_the_unread_bullets_but_not_zero( tmp_path ):
    manifest = f"## Session: {SID}\n### Touched Files\n- `{MY_FILE}`\n- the other one\n"
    reason   = _verdict( tmp_path, manifest, [ UNCLAIMED ] ).deny_reason
    assert "1 bullet(s) under your `### Touched Files` are in no form" in reason
    assert "- the other one" in reason
    assert "CLAIMS ZERO PATHS" not in reason


def test_a_long_unread_list_is_summarised( tmp_path ):
    bullets  = "\n".join( f"- prose line {n}" for n in range( 8 ) )
    reason   = _verdict( tmp_path, f"## Session: {SID}\n### Touched Files\n{bullets}\n",
                         [ UNCLAIMED ] ).deny_reason
    assert "- prose line 4" in reason and "- prose line 5" not in reason
    assert "… and 3 more" in reason


def test_a_fully_read_section_adds_no_hint( tmp_path ):
    """Negative control: the hint must not become boilerplate on every refusal."""
    manifest = f"## Session: {SID}\n### Touched Files\n- `{MY_FILE}`\n"
    reason   = _verdict( tmp_path, manifest, [ UNCLAIMED ] ).deny_reason
    assert reason.startswith( "`git commit` writes the WHOLE INDEX" )
    assert "Readable forms" not in reason


def test_a_size_only_refusal_carries_no_section_hint( tmp_path, monkeypatch ):
    """The hint is about ownership; a large file the section owns is not an ownership problem."""
    monkeypatch.setattr( guard, "LARGE_FILE_BYTES", 4 )
    ( tmp_path / "big.bin" ).write_bytes( b"0123456789" )
    manifest = f"## Session: {SID}\n### Touched Files\n- `big.bin`\n- unread prose\n"
    reason   = _verdict( tmp_path, manifest, [ "big.bin" ] ).deny_reason
    assert "LARGE FILE" in reason
    assert "Readable forms" not in reason


def test_a_clean_commit_from_a_drifted_section_stays_silent( tmp_path ):
    """Unread bullets alone never refuse — a clean commit is never refused (row 53c4900f)."""
    manifest = f"## Session: {SID}\n### Touched Files\n- `{MY_FILE}`\n- unread prose\n"
    verdict  = _verdict( tmp_path, manifest, [ MY_FILE ] )
    assert verdict.deny_reason is None and verdict.notice is None
