#!/usr/bin/env python3
"""
A2.6 (the event-name registry) and A2.7 (the generated API docs) for the console tee.

Plan: `src/rnd/v0.2.1/2026.09.27-console-tee-live-stream-plan.md`, sha256 2603385fd183,
with the two amendments Mr. Radio carried on 2026-09-27: A2.6 asserts SET EQUALITY
through ConfigurationManager rather than a count, and A2.7's generate-api-docs arm moved
into phase 1 — `api.json` must stay byte-identical and `api.md` may change only on its
footer line.

Why a count was the wrong assertion (A2.6)
------------------------------------------
"the list has 29 names" is satisfied by a list that has the four new names and has lost
one of the twenty-five committed ones — the arithmetic works out and the regression ships.
Set equality names every member, so a swap fails and the message says which name moved.
CLAUDE.md § Tests: "Trace both sides of a comparison back to their origin… pin one side
to a literal." The twenty-five are pinned as a literal here; the live side is read through
ConfigurationManager, which is the reader `websocket_manager.connect` validates against.

Why this matters more than it looks (T3)
----------------------------------------
A name absent from `websocket available events` is dropped at subscribe time, SILENTLY.
A client whose whole list validates to `[]` has every frame dropped while auth reports
success — the incident the in-place comment at `websocket_manager.py:207-219` describes.
So the registry entry is not bookkeeping: it is the difference between a stream and a
silence that reports itself as a success.

Venue: :7999-eligible
---------------------
A2.6 is a config read — no server, no network, sub-second.
A2.7 needs the live `:7999` server for `/openapi.json`, runs in well under two minutes,
and MUTATES NOTHING: it points the generator at a staging root under tmp_path seeded
with the committed files, so the real `src/docs/fastapi/` is never written. It is skipped
— explicitly and with a reason in the skip message — when no server is up, because a
docs-freshness check that silently passes without a server is worse than no check.
"""

import json
import os
import shutil
import subprocess
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
INI_PATH   = os.path.join( LUPIN_ROOT, "src", "conf", "lupin-app.ini" )
DOCS_DIR   = os.path.join( LUPIN_ROOT, "src", "docs", "fastapi" )
GENERATOR  = os.path.join( LUPIN_ROOT, "src", "scripts", "generate-api-docs.sh" )

WS_EVENTS_KEY = "websocket available events"

# The four names, per ruling OSQ-6 — `cc_transcript` prefix, and `update` became `append`.
CC_TRANSCRIPT_EVENTS = frozenset( [
    "cc_transcript_watch", "cc_transcript_unwatch", "cc_transcript_append", "cc_transcript_state",
] )

# The twenty-five names committed before this feature, read from lupin-app.ini:1729 on
# 2026-09-27 at sha 7db04b8af and pinned here as a LITERAL. This is the side of the
# comparison that must not be derived from the file under test — otherwise both sides
# move together and the assertion is a tautology.
COMMITTED_EVENTS_BEFORE = frozenset( [
    "audio_streaming_chunk", "audio_streaming_complete", "audio_streaming_status",
    "auth_error", "auth_request", "auth_success", "connect", "error",
    "job_paused", "job_removed", "job_resumed", "job_state_transition",
    "notification_expired", "notification_play_sound", "notification_queue_update",
    "notification_responded", "proxy_decision_new", "repair_cycle_update",
    "speakerphone_changed", "status", "sys_ping", "sys_pong", "sys_time_update",
    "tts_job_request", "update_subscriptions",
] )

EXPECTED_EVENTS = COMMITTED_EVENTS_BEFORE | CC_TRANSCRIPT_EVENTS


# ── A2.6 ──────────────────────────────────────────────────────────────────────

@pytest.fixture( scope="module" )
def configured_event_names():
    """
    The live event list, read through ConfigurationManager — the real reader.

    A2.6's amendment says "through ConfigurationManager, not a count". Reading the INI
    text directly would test the file; reading it through the manager tests what
    `websocket_manager.connect` will actually see, including any type coercion or
    whitespace handling the manager applies. CLAUDE.md § Tests: "A projection of a gate
    must ask the gate, not restate its rule."

    Ensures:
        - returns the configured names as a frozenset of stripped strings
    """
    from cosa.config.configuration_manager import ConfigurationManager

    # env_var_name ALONE — the manager refuses env_var_name together with config_path,
    # and this is the form its peers use (test_dm_tutor_prompt_keeps_the_subject.py:39).
    # It is also the right one: the env var is how the running server resolves its config,
    # so reading through it measures the same block the server will read.
    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    raw = config_mgr.get( WS_EVENTS_KEY, default=None )
    assert raw, (
        f"{WS_EVENTS_KEY!r} read as {raw!r} through ConfigurationManager. An empty or "
        f"missing list means every subscription validates to [] and every frame is "
        f"dropped while auth reports success (T3)."
    )
    return frozenset( name.strip() for name in str( raw ).split( "," ) if name.strip() )


@pytest.mark.parametrize( "event_name", sorted( CC_TRANSCRIPT_EVENTS ) )
def test_each_cc_transcript_event_is_registered_individually( configured_event_names, event_name ):
    """
    Each of the four by name, as its own case.

    One parametrised case per name so a failure says WHICH name is missing rather than
    "the set differs" — and so three registered names plus one typo cannot hide inside a
    single assertion's diff.
    """
    assert event_name in configured_event_names, (
        f"{event_name!r} is absent from {WS_EVENTS_KEY!r}. A client subscribing to it has "
        f"that name silently dropped at subscribe time (T3), so the console pane would "
        f"receive nothing while reporting a successful connection."
    )


def test_the_event_registry_is_exactly_the_committed_names_plus_the_four( configured_event_names ):
    """
    Set equality, which a count cannot give you.

    A count of 29 is satisfied by a list that gained the four and lost one of the
    twenty-five: the arithmetic balances and the regression ships. This names both
    directions — what is missing, and what appeared that nobody declared.
    """
    missing   = EXPECTED_EVENTS - configured_event_names
    unexpected = configured_event_names - EXPECTED_EVENTS

    assert not missing, (
        f"{len( missing )} declared event name(s) absent from the INI: {sorted( missing )}"
    )
    assert not unexpected, (
        f"{len( unexpected )} event name(s) present in the INI that this test does not "
        f"know about: {sorted( unexpected )}. If they are intended, add them to "
        f"COMMITTED_EVENTS_BEFORE with a dated note — this assertion exists so a name "
        f"cannot arrive unreviewed."
    )


def test_the_four_names_are_not_already_among_the_committed_twenty_five():
    """
    The test's own premise, checked.

    If a `cc_transcript_*` name were already in the pinned twenty-five, the set-equality
    assertion above would pass whether or not this feature registered anything — the
    union would be unchanged. This is the guard on that: it proves the four names are new
    work, so the assertion above is measuring this feature and not restating the status
    quo.
    """
    assert not ( CC_TRANSCRIPT_EVENTS & COMMITTED_EVENTS_BEFORE )
    assert len( COMMITTED_EVENTS_BEFORE ) == 25, (
        f"the pinned literal holds {len( COMMITTED_EVENTS_BEFORE )} names, not the 25 it "
        f"was read as. Re-read lupin-app.ini and date the change."
    )
    assert len( EXPECTED_EVENTS ) == 29


# ── A2.7 ──────────────────────────────────────────────────────────────────────

def _server_is_up():
    """
    True when :7999 answers /openapi.json.

    Uses urllib rather than curl — CLAUDE.md prohibits curl for API testing and health
    checks. (The generator script itself uses curl internally; that is its business, and
    changing it is not this test's scope.)
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen( "http://localhost:7999/openapi.json", timeout=5 ) as response:
            return response.status == 200
    except ( urllib.error.URLError, OSError, TimeoutError ):
        return False


@pytest.fixture
def staging_root( tmp_path ):
    """
    A LUPIN_ROOT the generator can write into, seeded with the committed docs.

    `generate-api-docs.sh` derives `DOCS_DIR="$LUPIN_ROOT/src/docs/fastapi"` and
    `VENV_PYTHON="$LUPIN_ROOT/.venv/bin/python3"`, so pointing LUPIN_ROOT at a staging
    tree redirects every write it makes. That is what keeps this test non-mutating: the
    real `src/docs/fastapi/` is read and never written, so the tier stays :7999-eligible
    and a failing run leaves no repair work behind.

    Ensures:
        - yields a path whose src/docs/fastapi holds copies of the committed api.json
          and api.md, and whose .venv points at the real one
    """
    root = tmp_path / "staging"
    ( root / "src" / "docs" / "fastapi" ).mkdir( parents=True )
    ( root / "src" / "scripts" ).mkdir( parents=True )

    for name in ( "api.json", "api.md" ):
        shutil.copyfile( os.path.join( DOCS_DIR, name ), root / "src" / "docs" / "fastapi" / name )
    shutil.copyfile( GENERATOR, root / "src" / "scripts" / "generate-api-docs.sh" )
    os.chmod( root / "src" / "scripts" / "generate-api-docs.sh", 0o755 )
    ( root / ".venv" ).symlink_to( os.path.join( LUPIN_ROOT, ".venv" ) )

    return root


def _footer_split( markdown ):
    """
    Split api.md into ( body, footer_line ).

    The generator appends a blank line, a `---` rule and one `_Auto-generated on …_` line
    on every run, so that last line ALWAYS differs and the body never should. Naming the
    footer by its own marker rather than by a line count means a body that grows or
    shrinks does not move the split.

    Requires:
        - markdown is the file's text

    Ensures:
        - returns ( body_without_the_footer_line, the_footer_line )
        - raises AssertionError if the footer marker is not the last non-empty line
    """
    lines = markdown.rstrip( "\n" ).split( "\n" )
    assert lines[ -1 ].startswith( "_Auto-generated on " ), (
        f"the last line of api.md is not the generated footer: {lines[ -1 ][ :80 ]!r}. "
        f"This test's body/footer split depends on it."
    )
    return "\n".join( lines[ :-1 ] ), lines[ -1 ]


@pytest.mark.skipif( not _server_is_up(), reason=(
    "A2.7 needs the live :7999 server to fetch /openapi.json. NOT a pass — the committed "
    "API docs are UNVERIFIED for this run. Bounce :7999 "
    "(./src/scripts/bounce-dev-server.sh) and re-run."
) )
def test_regenerating_the_api_docs_leaves_api_json_byte_identical( staging_root ):
    """
    A2.7's core: a re-run that changes `api.json` means the committed spec was stale.

    Byte-identical, not semantically equal — the file is pretty-printed by
    `python -m json.tool`, so its bytes are deterministic for a given spec, and a byte
    comparison catches a reordering that a dict comparison would forgive.

    ⚠️ This test only means something against a server running the CODE UNDER REVIEW. The
    `:7999` container serves a static snapshot from its last spin-up, so a phase-1 router
    that has not been bounced in is invisible to it — a green here would then be about the
    previous build. Bounce before believing it.
    """
    before = open( os.path.join( DOCS_DIR, "api.json" ), "rb" ).read()

    environment = dict( os.environ, LUPIN_ROOT=str( staging_root ) )
    result = subprocess.run(
        [ str( staging_root / "src" / "scripts" / "generate-api-docs.sh" ) ],
        env=environment, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"the generator exited {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    after = open( staging_root / "src" / "docs" / "fastapi" / "api.json", "rb" ).read()
    assert after == before, (
        f"api.json changed on regeneration ({len( before ):,} bytes committed, "
        f"{len( after ):,} bytes generated). The committed OpenAPI spec is stale — a "
        f"router or a decorator changed without src/scripts/generate-api-docs.sh being "
        f"re-run. Regenerate it in the real tree and commit the result."
    )


@pytest.mark.skipif( not _server_is_up(), reason=(
    "A2.7 needs the live :7999 server to fetch /openapi.json. NOT a pass — the committed "
    "API docs are UNVERIFIED for this run."
) )
def test_regenerating_the_api_docs_changes_api_md_only_on_its_footer_line( staging_root ):
    """
    A2.7's second half: `api.md` may differ on its timestamp footer and nowhere else.

    The footer is appended unconditionally by the generator (it shells `date` into the
    file), so requiring api.md to be byte-identical would fail every run for a reason that
    is not a defect. Requiring the BODY to be identical is the assertion that has content.
    """
    committed_body, committed_footer = _footer_split( open( os.path.join( DOCS_DIR, "api.md" ), encoding="utf-8" ).read() )

    environment = dict( os.environ, LUPIN_ROOT=str( staging_root ) )
    result = subprocess.run(
        [ str( staging_root / "src" / "scripts" / "generate-api-docs.sh" ) ],
        env=environment, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"the generator exited {result.returncode}\n{result.stderr}"

    generated_body, generated_footer = _footer_split(
        open( staging_root / "src" / "docs" / "fastapi" / "api.md", encoding="utf-8" ).read()
    )

    assert generated_body == committed_body, (
        "api.md's BODY changed on regeneration, so the committed API documentation is "
        "stale. Only the _Auto-generated on …_ footer is allowed to move."
    )
    # The footer is EXPECTED to differ. Asserting that it does is what proves the
    # generator actually ran and wrote this file — without it, a no-op that copied the
    # input forward would satisfy the body assertion perfectly.
    assert generated_footer != committed_footer, (
        "the footer is unchanged, so the generator may not have written api.md at all — "
        "the body comparison above would then be comparing the seed against itself"
    )


@pytest.mark.skipif( not _server_is_up(), reason="needs :7999 for /openapi.json" )
def test_the_generated_spec_names_the_cc_transcript_rest_path( staging_root ):
    """
    A2.7 is a documentation check, and this is the token it is checking for.

    Checked by TOKEN rather than by judgement (A7): the REST path ruled by OSQ-6 must
    appear as a path key in the spec the live server produces. A spec that does not
    mention it is a spec taken before the router was mounted — which is exactly the
    stale-snapshot case the bounce is for.
    """
    environment = dict( os.environ, LUPIN_ROOT=str( staging_root ) )
    subprocess.run(
        [ str( staging_root / "src" / "scripts" / "generate-api-docs.sh" ) ],
        env=environment, capture_output=True, text=True, timeout=120, check=True,
    )
    spec  = json.load( open( staging_root / "src" / "docs" / "fastapi" / "api.json", encoding="utf-8" ) )
    paths = spec.get( "paths", {} )

    matching = [ path for path in paths if path.startswith( "/api/cc-transcript/" ) ]
    assert matching, (
        f"no /api/cc-transcript/ path in the generated spec ({len( paths )} paths total). "
        f"Either the router is not mounted, or :7999 is serving a snapshot from before it "
        f"landed — bounce it and re-run."
    )
    # The legacy name ruling OSQ-6 superseded must not be there too, or both doors exist.
    assert not [ p for p in paths if p.startswith( "/api/transcript/" ) ], (
        "the superseded /api/transcript/ path is still mounted; OSQ-6 replaced it with "
        "/api/cc-transcript/ and 'transcript' already means speech-to-text in the mux"
    )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
