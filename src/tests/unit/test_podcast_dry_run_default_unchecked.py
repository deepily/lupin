"""
Regression guard for finding ee4a4cb7 #1 — the podcast Dry Run checkbox must
ship UNCHECKED.

A dry-run podcast writes NO script and NO mp3 (job.py:455-457, "mock - not
actually created"), and its completion card (job.py:453-459) is plain text with
NO clickable Play Here — that link only builds in the real completion path
(job.py:343-349, gated on `if audio_rel`). If the checkbox ships CHECKED, a user
who submits without touching it reaches "🧪 Dry Run Complete" with mock paths and
nothing to play. Rick's ruling (2026-08-04): flip the default to UNCHECKED so the
default submit produces a real, playable podcast.

This is a STATIC / pure-Python guard (:7999-eligible — no server, no state
mutation). The real-browser end-to-end proof (submit → real render → Play Here)
lives in the e2e_ui Playwright suites; this file guards the markup default so the
box cannot silently drift back to `checked`.

Scope: ONLY the podcast card's dry-run checkbox is asserted unchecked (Rick's
demo path). The other dry-run checkboxes (research / SWE / presentation /
test-suite / claude-code) are intentionally left CHECKED and are out of scope
for this finding.
"""

import os
import re

import cosa.utils.util as cu

STATIC     = os.path.join( cu.get_project_root(), "src", "lupin_app", "static" )
NOTIF_HTML = os.path.join( STATIC, "html", "notifications.html" )

# the podcast dry-run <input>, matched by its stable data-testid, up to the tag close
PODCAST_DRY_RUN_INPUT_RE = re.compile(
    r'<input[^>]*data-testid="notifications-podcast-dry-run-checkbox"[^>]*/?>'
)


def _read( path ):
    with open( path, encoding="utf-8" ) as fh:
        return fh.read()


def test_podcast_dry_run_input_is_present():
    """Non-vacuity anchor: the podcast dry-run input must still exist by testid.

    If the markup is reshaped and the testid changes, the unchecked assertion
    below would match nothing and pass VACUOUSLY — this fails loudly instead.
    """
    match = PODCAST_DRY_RUN_INPUT_RE.search( _read( NOTIF_HTML ) )
    assert match, (
        "notifications.html must carry an <input data-testid="
        "'notifications-podcast-dry-run-checkbox'> — the podcast dry-run checkbox"
    )


def test_podcast_dry_run_ships_unchecked():
    """The podcast dry-run checkbox must NOT carry the `checked` attribute.

    Finding ee4a4cb7 #1: shipping checked means a default submit yields a mock
    completion card with nothing to play. Rick's ruling flips the default to
    unchecked.
    """
    match = PODCAST_DRY_RUN_INPUT_RE.search( _read( NOTIF_HTML ) )
    assert match, "podcast dry-run input not found (see non-vacuity test)"
    input_tag = match.group( 0 )
    assert "checked" not in input_tag, (
        "podcast dry-run checkbox ships CHECKED — a default submit produces a "
        "dry-run (no mp3, no Play Here). Remove the `checked` attribute so the "
        f"default is a real, playable podcast. Offending tag: {input_tag}"
    )
