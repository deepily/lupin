"""
E2E — prove Tiffany's fail-open podcast approval gate LIVE (commit 414009c3).

WHAT THIS PROVES, AND WHY A UNIT TEST CANNOT
--------------------------------------------
Every committed unit test in `test_podcast_generator.py` MOCKS
`voice_io.present_choices` — even the do_all_async test hands the orchestrator a
canned `{"default_used": True}`. So the committed suite proves the orchestrator
HANDLES a fail-open answer; it does NOT prove a fail-open answer ever gets
PRODUCED. Those are different claims and only one was tested (Clayton's review of
414009c3, confirmed by Mr Radio). This test closes the gap: it drives the REAL
core `voice_io` fail-open seam against a REAL server whose gate REALLY times out.

THE CHAIN, END TO END, NOTHING MOCKED IN THE MIDDLE:
  online-but-silent gate → SSE waits the (shortened) review timeout →
  server returns exit_code=2 → dispatcher raises VoiceGateTimeoutError →
  core voice_io `_resolve_default` returns {header: "Approve script",
  default_used: True} → orchestrator advances to OrchestratorState.GENERATING_AUDIO.

ONLINE-SILENT, NOT OFFLINE (the sharp distinction, Clayton 2026-08-03)
---------------------------------------------------------------------
`voice_io` does NOT forward `response_default` to the server (voice_io.py:866),
so an OFFLINE user 503s IMMEDIATELY — no timer runs. The timeout override only
bites when the user is ONLINE but SILENT (present, never clicks) — Rick's actual
demo case (looking away, browser up). So this test holds a REAL authenticated
queue WebSocket open (never answering) to make the target count as connected, and
shortens the review timeout to a few seconds so the timer genuinely fires and
expires within the test.

ASSERT-AND-STOP AT THE BILLING SEAM (Mr Radio's ruling, do NOT "strengthen")
----------------------------------------------------------------------------
The proof asserts INSIDE `_generate_audio_async` — the first method that would
bill ElevenLabs — that `self.state == GENERATING_AUDIO`, then aborts. Asserting
inside the method that would bill proves the run GOT there, and pays for no audio.
Because the orchestrator ignores `default_used` when advancing (it reads the raw
answer), the audio phase cannot behave differently for a silence-approval than a
human one — so reaching this method IS the proof of the chain, not a proxy for it.
DO NOT replace this with a full-mp3 run: it would buy nothing this test asserts.

THE default_used SPY (stops a false green)
------------------------------------------
Reaching GENERATING_AUDIO alone would still go green if a human-shaped answer
somehow arrived. So we ALSO assert `script_auto_approved is True` — the orchestrator
records `bool(choice.get("default_used"))` at approval (orch:493). Only a
fail-open (silence-resolved) answer sets it True; a real selection leaves it False.
That is what pins the green to "the default resolved", not merely "audio was reached".

VENUE — own-server (throwaway migrated Postgres), NOT :7999/:8000
----------------------------------------------------------------
Reuses the handback E2E harness (`_handback_e2e_server.py` + its fixtures) — the
precedented home for real-notify-timeout E2Es (TODO.md 2026-08-02 venue finding).
Near-zero spend (canned script, aborted audio), no :8000 monopoly, does not touch
lupin_db_dev. SKIPS when Postgres is unreachable.

Only the gate timeout is live; research/analysis/script-gen/save are canned IN
THIS TEST (never in the tree) so `do_all_async` reaches the gate deterministically
in ~1s and the sole live variable is the fail-open resolution.
"""

import os
import uuid
import asyncio

import pytest

# Reuse the handback own-server harness verbatim: throwaway-DB fixture, the real
# router server boot, the online-user WS holder, and the bridge seeder. Importing
# it also pins JWT_SECRET_KEY / AUTH_MODE=jwt at module import (its side effects).
from cosa.agents.podcast_generator.orchestrator import (
    PodcastOrchestratorAgent,
    OrchestratorState,
)
from cosa.agents.podcast_generator.config import PodcastConfig
from cosa.agents.podcast_generator.state import PodcastScript, ScriptSegment
from cosa.agents.podcast_generator import cosa_interface as podcast_cosa_interface
from cosa.agents.podcast_generator import voice_io as podcast_voice_io
from cosa.agents.utils import voice_io as core_voice_io

from src.tests.e2e.test_ask_answer_handback import (          # noqa: E402
    handback_ctx,
    _boot_server,
    _OnlineUser,
    _seed_bridge,
    _HUMAN_EMAIL,
    _HUMAN_KEY,
)


_REVIEW_TIMEOUT_S = 3          # shortened so the online-silent timer fires inside the test
_SENDER_HASH8     = "cc111111"  # bridge prefix so the ask row stamps a sender_persona


class _ReachedAudioPhase( Exception ):
    """Sentinel — raised inside the patched audio method to abort before ElevenLabs bills."""


def _canned_script() -> PodcastScript:
    """A minimal 2-segment script so the gate has real content to present."""
    return PodcastScript(
        title           = "Fail-Open Gate Proof",
        research_source  = "canned://fail-open-proof",
        host_a_name      = "Ada",
        host_b_name      = "Boris",
        segments         = [
            ScriptSegment( speaker="Ada",   role="curious", text="Does silence continue?" ),
            ScriptSegment( speaker="Boris", role="expert",  text="On this gate, yes — it fails open." ),
        ],
        estimated_duration_minutes = 1.0,
    )


@pytest.fixture
def live_gate_ctx( handback_ctx, tmp_path ):
    """
    Boot the real-router own-server, hold a silent authenticated WS open as the
    target human (so the gate's target counts as CONNECTED), and point the podcast
    dispatcher at that server. Tears the WS + server down after.
    """
    ctx        = handback_ctx
    bridge_dir = str( tmp_path / "bridges" )
    _seed_bridge( bridge_dir, _SENDER_HASH8, "Clayton" )

    server = _boot_server( ctx, bridge_dir )
    base   = f"http://127.0.0.1:{server.port}"

    # ONLINE but SILENT: a real authenticated queue WS that never answers. Session
    # id is arbitrary; auth maps it to the human user so is_user_connected() is True.
    online = _OnlineUser( server.port, session_id="clayton-silent-0000", jwt=ctx[ "human_jwt" ] )
    online.start()

    try:
        yield { "base": base, "ctx": ctx, "server": server }
    finally:
        online.stop()
        server.stop()


def test_online_silent_gate_times_out_defaults_and_reaches_audio( live_gate_ctx, monkeypatch ):
    """
    Drive `do_all_async` with a REAL online-silent gate at a ~3s timeout and assert
    the chain fires live: the gate times out, the core voice_io default resolves to
    "Approve script" (default_used=True), and the orchestrator reaches
    GENERATING_AUDIO — asserted inside the method that would bill, then aborted.
    """
    ctx  = live_gate_ctx[ "ctx" ]
    base = live_gate_ctx[ "base" ]

    # ── Route the dispatcher at the throwaway server + authenticate as the human ──
    monkeypatch.setenv( "LUPIN_APP_SERVER_URL", base )
    # notify_user_sync loads its api key via config_loader; force it to the seeded key.
    import cosa.utils.config_loader as config_loader
    monkeypatch.setattr( config_loader, "load_api_key", lambda *a, **k: _HUMAN_KEY )
    # Target the seeded human (email → connected UUID resolved server-side).
    monkeypatch.setattr( podcast_cosa_interface, "TARGET_USER", _HUMAN_EMAIL )

    # ── Force the REAL voice dispatch path (not the no-tty non-interactive shortcut,
    #    which would resolve the default WITHOUT ever calling the server / timing out) ──
    podcast_voice_io.reconfigure()
    monkeypatch.setattr( core_voice_io, "_force_cli_mode", False )
    monkeypatch.setattr( core_voice_io, "_voice_available", True )

    # ── Build the orchestrator: canned upstream, shortened gate, English-only ──
    config = PodcastConfig()
    config.script_review_timeout_seconds = _REVIEW_TIMEOUT_S

    orch = PodcastOrchestratorAgent(
        research_doc_path = "canned://fail-open-proof",
        user_id           = ctx[ "human_id" ],
        config            = config,
        target_languages  = [ "en" ],
    )

    captured = { "state_at_audio": None }

    import types
    async def _fake_load( *a, **k ):     return "canned research content"
    async def _fake_analyze( *a, **k ):  return types.SimpleNamespace( main_topic="fail-open proof" )
    async def _fake_script( *a, **k ):   return _canned_script()
    async def _fake_save( *a, **k ):     return "/tmp/fail-open-proof-script.md"

    async def _assert_and_abort( self_inner, *a, **k ):
        # The billing seam. Reaching here proves the gate resolved and the run
        # advanced; capture the state and abort before any ElevenLabs call.
        captured[ "state_at_audio" ] = self_inner.state
        raise _ReachedAudioPhase()

    monkeypatch.setattr( orch, "_load_research_async",    _fake_load )
    monkeypatch.setattr( orch, "_analyze_content_async",  _fake_analyze )
    monkeypatch.setattr( orch, "_generate_script_async",  _fake_script )
    monkeypatch.setattr( orch, "_save_script_async",      _fake_save )
    monkeypatch.setattr(
        PodcastOrchestratorAgent, "_generate_audio_async", _assert_and_abort
    )

    # ── Run: the gate is the ONLY live element; it must time out (~3s) and default ──
    with pytest.raises( _ReachedAudioPhase ):
        asyncio.run( orch.do_all_async() )

    # ── The chain fired live ──
    assert captured[ "state_at_audio" ] == OrchestratorState.GENERATING_AUDIO, (
        f"reached audio phase but state was {captured[ 'state_at_audio' ]!r}, "
        f"not GENERATING_AUDIO"
    )
    # default_used spy: only a silence-resolved (fail-open) answer sets this True.
    assert orch._podcast_state.get( "script_auto_approved" ) is True, (
        "reached audio but script_auto_approved is not True — a human-shaped answer "
        "arrived instead of the fail-open default; the green would be for the wrong reason"
    )
