"""
Guard: a manifest entry whose path carries a parenthetical note must still claim
the FILE, not the annotated string.

WHY THIS EXISTS. `_TOUCHED_RE` captures everything after the pipe as the path, so
a long-standing manifest convention —

    - 2026-08-29T23:33:00 | src/scripts/watch-hook-events.py (merge 27f993b9 — maya)

— claimed the literal string `src/scripts/watch-hook-events.py (merge 27f993b9 —
maya)`. No file equals that, so the section claimed nothing for that file, and a
commit naming it was refused with "claimed by no session": the guard blocking
work it exists to permit.

MEASURED 2026-09-01 against the live `.claude-session.md`: 332 claimed paths
across 27 sections, **10 mis-claimed this way** — six in one seat's own section
(every merge annotation), four more carrying DELETED / renamed notes.

THE PARSE NEVER FAILED. It succeeded and produced a wrong answer, which is why
nothing surfaced it and why it was diagnosed from symptoms as "the parse breaks"
before anyone ran it. A refusal is loud; a wrong claim is silent.

WHAT WAS TESTED AND FOUND NOT TO BE THE CAUSE. A wrapped `**Commits**:` line and
a following warning paragraph were proposed as a second mechanism — non-entry
lines being read as paths. Measured against the live section that has exactly
that shape (`c1e89652`): it parses 6 claims, all real files. `_TOUCHED_RE`
requires `- <ts> | <path>`, and a wrapped prose line matches neither. Recorded
because a disproved mechanism is worth as much as a proved one — it stops the
next reader re-testing it.
"""
from lupin_cli.claude_code.hooks.lib.commit_scope_guard import _parse_manifest


def _claims( line ):
    """
    Ensures:
        - returns the set of paths one manifest line claims for one session
    """
    return _parse_manifest( f"## Session: 37316fd2\n### Touched Files\n{line}\n" )[ "37316fd2" ]


def test_a_bare_path_is_claimed_unchanged():
    """The ordinary case must not move."""
    assert _claims( "- 2026-09-01T19:29:00 | src/tests/smoke/foo.py" ) == { "src/tests/smoke/foo.py" }


def test_a_merge_annotation_still_claims_the_file():
    """The measured defect: six live entries in one section had this shape."""
    got = _claims( "- 2026-08-29T23:33:00 | src/scripts/watch-hook-events.py (merge 27f993b9 — maya)" )
    assert "src/scripts/watch-hook-events.py" in got, (
        "the annotated form claims a string no file equals — the section claims nothing"
    )


def test_a_deleted_annotation_still_claims_the_file():
    assert "src/scripts/run-lupin-gui.sh" in _claims(
        "- 2026-08-26T20:45:00 | src/scripts/run-lupin-gui.sh (DELETED — only caller of src/lib)"
    )


def test_the_annotated_string_is_also_kept():
    """
    Both forms are claimed. The raw string preserves prior behaviour for any real
    path that legitimately contains " (", so this fix cannot take a claim away.
    """
    raw = "src/scripts/watch-hook-events.py (merge 27f993b9 — maya)"
    assert raw in _claims( f"- 2026-08-29T23:33:00 | {raw}" )


def test_a_path_with_no_note_gains_nothing_extra():
    """The bare-path rule must not fire on an unannotated entry."""
    assert _claims( "- 2026-09-01T19:29:00 | src/a/b.py" ) == { "src/a/b.py" }


def test_a_wrapped_prose_line_is_not_read_as_a_path():
    """
    The mechanism that was PROPOSED and disproved. A `**Commits**:` line, its
    wrapped continuation, and a following warning paragraph must contribute
    nothing — `_TOUCHED_RE` requires `- <ts> | <path>`.
    """
    text = (
        "## Session: c1e89652\n"
        "### Touched Files\n"
        "- 2026-09-01T19:35:00 | .claude-session.md\n"
        "\n"
        "**Commits**: `a936601f` (carries another seat's content — see the note in that\n"
        "test file), `1cc20271`, `c2aa3cd4`\n"
        "\n"
        "THIS SECTION DID NOT EXIST UNTIL 19:35, AND ITS ABSENCE DISABLED THE GUARD.\n"
    )
    assert _parse_manifest( text )[ "c1e89652" ] == { ".claude-session.md" }
