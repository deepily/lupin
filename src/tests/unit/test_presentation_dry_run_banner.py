"""
Unit test: the CLI dry-run banner must describe what the REACHABLE dry-run path
actually does — not assert work that never happens.

Row b475d11b defect 2: __main__.py printed "[DRY RUN MODE — Real ingest, mock
analysis/outline/elaborate, real YAML serialization]" while the only reachable
dry-run (job._execute_dry_run) skips ingest, skips analysis/outline/elaborate,
skips YAML serialization, and writes nothing. A green that lies teaches the
runner to trust a false message. This test pins the banner to the behaviour.

Venue: :7999 (unit, no server, no inference).
"""

import asyncio
import types

import pytest

import cosa.agents.presentation_generator.__main__ as pg_main
import cosa.agents.presentation_generator.job as pg_job


def _args( source_path: str ) -> types.SimpleNamespace:
    """A minimal argparse-shaped namespace for run_presentation_generation."""
    return types.SimpleNamespace(
        source                  = source_path,
        user_id                 = "u1",
        user_email              = "a@b.c",
        session_id              = "s1",
        target_duration_minutes = None,
        target_slide_count      = None,
        audience                = None,
        audience_context        = None,
        theme                   = None,
        dry_run                 = True,
        debug                   = False,
        verbose                 = False,
    )


class _FakeJob:
    """Stands in for PresentationGeneratorJob so the banner branch runs without a real build."""
    def __init__( self, **kwargs ):
        self.id_hash               = "deadbeef"
        self.answer_conversational = None
    async def _execute( self ):
        return "Dry Run Complete (mock summary)."


def test_dry_run_banner_states_what_the_code_does_not_a_false_claim( tmp_path, monkeypatch, capsys ):
    source = tmp_path / "outline.md"
    source.write_text( "# Outline\n\nSome content.\n" )
    monkeypatch.setattr( pg_job, "PresentationGeneratorJob", _FakeJob )

    rc = asyncio.run( pg_main.run_presentation_generation( _args( str( source ) ) ) )
    out = capsys.readouterr().out

    assert rc == 0
    # The retired lie must be gone: the reachable path does NEITHER of these.
    assert "Real ingest" not in out
    assert "real YAML serialization" not in out
    # The banner must state the truth: it skips the phases and writes nothing.
    assert "DRY RUN MODE" in out
    assert "skips ingest" in out
    assert "writes nothing to disk" in out


class _CaptureVoiceIO:
    """Captures notify() abstracts so the completion-stats claim can be asserted."""
    def __init__( self ):
        self.abstracts = []
    def set_job_id( self, job_id ): pass
    def clear_job_id( self ): pass
    async def notify( self, message, priority=None, abstract=None, job_id=None, queue_name=None ):
        if abstract is not None:
            self.abstracts.append( abstract )


class _FakeCosaInterface:
    SENDER_ID   = None
    TARGET_USER = None
    def _get_sender_id( self, suffix=None ):
        return "sender"


def test_dry_run_completion_stats_report_slide_count_zero_not_a_fabricated_number():
    """The completion abstract must not assert a fabricated slide count. Row b475d11b:
    it printed '15 slides' while slide_count is structurally 0. Pins the stat to the
    real artifact value so it can never drift back to a made-up number."""
    fake_self = types.SimpleNamespace(
        source_path        = "/tmp/outline.md",
        user_email         = "a@b.c",
        id_hash            = "deadbeef",
        base_id            = "base",
        artifacts          = {},
        force_failure_mode = False,
        cost_summary       = None,
        debug              = False,
        yaml_path          = None,
        marp_path          = None,
    )
    voice = _CaptureVoiceIO()
    asyncio.run(
        pg_job.PresentationGeneratorJob._execute_dry_run( fake_self, voice, _FakeCosaInterface() )
    )
    stats = "\n".join( voice.abstracts )
    assert "15 slides" not in stats
    assert "slide_count=0" in stats          # tied to the real artifact value, not a literal
    assert fake_self.artifacts[ "slide_count" ] == 0


def test_reachable_dry_run_writes_nothing_to_disk( monkeypatch, tmp_path ):
    """Behaviour, not source text (John's review): the banner promises the dry-run
    'writes nothing to disk', so PROVE it — spy on open() and assert the reachable
    path opens no file for writing while running. Deleting the real skip logic but
    keeping the notify strings would go RED here (unlike a source-grep)."""
    import builtins
    write_opens = []
    real_open   = builtins.open
    def _spy_open( path, mode="r", *a, **kw ):
        if any( m in mode for m in ( "w", "a", "x", "+" ) ):
            write_opens.append( ( str( path ), mode ) )
        return real_open( path, mode, *a, **kw )
    monkeypatch.setattr( builtins, "open", _spy_open )

    fake_self = types.SimpleNamespace(
        source_path        = str( tmp_path / "outline.md" ),
        user_email         = "a@b.c",
        id_hash            = "deadbeef",
        base_id            = "base",
        artifacts          = {},
        force_failure_mode = False,
        cost_summary       = None,
        debug              = False,
        yaml_path          = None,
        marp_path          = None,
    )
    asyncio.run(
        pg_job.PresentationGeneratorJob._execute_dry_run( fake_self, _CaptureVoiceIO(), _FakeCosaInterface() )
    )
    assert write_opens == []                                  # no file written = "writes nothing to disk"
    assert list( tmp_path.iterdir() ) == []                   # and the working dir stays empty
