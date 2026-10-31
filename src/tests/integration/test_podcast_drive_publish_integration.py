#!/usr/bin/env python3
"""
Integration tests for the podcast jobs and the Drive publisher hook.

Both podcast jobs run their real execute path. The orchestrator and voice I/O are stubbed,
and a fake publisher stands in for Google, so no Drive call and no speech spend can happen.

A dry run with publishing on never builds or calls the publisher. A real run calls it once,
with each language mp3 and the source path joined to the project root. The done card then
carries the folder link.

The fake replaces the hook's publisher builder. The hook is shared by PodcastGeneratorJob
and DeepResearchToPodcastJob.
"""
import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.podcast_generator.config import PodcastConfig
from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
from cosa.agents.podcast_generator.job import PodcastGeneratorJob

FOLDER_LINK = "https://drive.google.com/drive/folders/FAKE-FOLDER"

CONFIG_FLAGS = {
    "publish_to_google_drive"      : True,
    "drive_folder_name"            : "Lupin Podcasts",
    "drive_upload_script"          : False,
    "drive_upload_source_document" : True,
}


class FakePublisher:
    """Records every publish_job call; never touches Google."""

    def __init__( self ):
        self.publish_calls = []

    def publish_job( self, job_folder_name, files ):
        self.publish_calls.append( ( job_folder_name, list( files ) ) )
        return {
            "folder_link" : FOLDER_LINK,
            "files"       : [ { "path": str( p ), "file_id": f"id{i}", "error": None,
                                "web_view_link": f"https://drive.google.com/file/d/{i}" }
                              for i, ( p, _m ) in enumerate( files ) ],
        }


@pytest.fixture
def fake_publisher( monkeypatch ):
    """Install the fake at the hook's seam; record every construction request."""
    from cosa.agents.podcast_generator import drive_hook
    pub   = FakePublisher()
    built = []
    def _make( config ):
        built.append( config )
        return pub
    monkeypatch.setattr( drive_hook, "_make_publisher", _make )
    pub.built = built
    return pub


def _config_with_publishing_on( *args, **kwargs ):
    cfg = PodcastConfig()
    for name, value in CONFIG_FLAGS.items():
        setattr( cfg, name, value )
    return cfg


def _voice_modules( pkg_name ):
    voice_io = MagicMock()
    voice_io.notify = AsyncMock()
    cosa_interface = MagicMock()
    cosa_interface._get_sender_id.return_value = "sender-id"
    pkg = types.ModuleType( pkg_name )
    pkg.voice_io       = voice_io
    pkg.cosa_interface = cosa_interface
    pkg.__path__       = []
    return pkg


def _make_files( root, langs ):
    ( root / "io" / "dr" ).mkdir( parents=True )
    ( root / "io" / "pod" ).mkdir( parents=True )
    source = root / "io" / "dr" / "report.md"
    source.write_text( "# source" )
    audio  = { l: str( root / f"io/pod/{l}.mp3" ) for l in langs }
    script = { l: str( root / f"io/pod/{l}.md" )  for l in langs }
    for p in list( audio.values() ) + list( script.values() ):
        open( p, "w" ).write( "x" )
    return source, audio, script


def _pg_modules( audio, script ):
    orch = MagicMock()
    orch.podcast_id = "pg-int"
    orch._podcast_state = {
        "final_audio_path"         : next( iter( audio.values() ) ),
        "final_script_path"        : next( iter( script.values() ) ),
        "audio_paths_by_language"  : audio,
        "script_paths_by_language" : script,
    }
    seg = MagicMock()
    seg.get_segment_count.return_value = 3
    seg.estimated_duration_minutes     = 5.0
    orch.do_all_async = AsyncMock( return_value=seg )
    orch._api_client  = None
    orch_mod = types.ModuleType( "cosa.agents.podcast_generator.orchestrator" )
    orch_mod.PodcastOrchestratorAgent = MagicMock( return_value=orch )
    return {
        "cosa.agents.podcast_generator"              : _voice_modules( "cosa.agents.podcast_generator" ),
        "cosa.agents.podcast_generator.orchestrator" : orch_mod,
    }


def _dr_modules():
    return { "cosa.agents.deep_research": _voice_modules( "cosa.agents.deep_research" ) }


def _dr_result( source, audio, script ):
    from cosa.agents.deep_research_to_podcast.state import PipelineState
    return types.SimpleNamespace(
        state=PipelineState.COMPLETED, error=None,
        research_path=str( source ), research_abstract="abs",
        audio_path=next( iter( audio.values() ) ), script_path=next( iter( script.values() ) ),
        pg_artifacts={ "audio_paths_by_language": audio, "script_paths_by_language": script },
        dr_cost=0.0, pg_cost=0.0, total_cost=0.0,
    )


def _pg_job( **kw ):
    return PodcastGeneratorJob( research_path="io/dr/report.md", user_id="u1",
                                user_email="u@test.com", session_id="s1", **kw )


def _dr_job( **kw ):
    return DeepResearchToPodcastJob( query="q", user_id="u1", user_email="u@test.com",
                                     session_id="s1", **kw )


# ---------------------------------------------------------------- (a) dry run never publishes
def test_pg_dry_run_with_publishing_on_never_calls_the_publisher( fake_publisher ):
    job = _pg_job( dry_run=True )
    with patch.dict( sys.modules, _pg_modules( { "en": "/x/en.mp3" }, { "en": "/x/en.md" } ) ), \
         patch.object( PodcastConfig, "from_config", side_effect=_config_with_publishing_on ), \
         patch( "asyncio.sleep", new=AsyncMock() ):
        asyncio.run( job._execute() )
    assert fake_publisher.built == [] and fake_publisher.publish_calls == []
    assert "drive_folder_link" not in job.artifacts
    assert job.artifacts[ "podcast_id" ].startswith( "dry-run-" )       # really the dry-run path


def test_dr_dry_run_with_publishing_on_never_calls_the_publisher( fake_publisher ):
    job = _dr_job( dry_run=True )
    with patch.dict( sys.modules, _dr_modules() ), \
         patch.object( PodcastConfig, "from_config", side_effect=_config_with_publishing_on ), \
         patch( "asyncio.sleep", new=AsyncMock() ):
        asyncio.run( job._execute() )
    assert fake_publisher.built == [] and fake_publisher.publish_calls == []
    assert "drive_folder_link" not in job.artifacts
    assert job.research_path.endswith( "/report.md" ) and "dry-run" in job.research_path


# ---------------------------------------------------------------- (b) real run publishes
def _assert_published( fake_publisher, job, source, audio, script ):
    assert len( fake_publisher.publish_calls ) == 1
    _folder, files = fake_publisher.publish_calls[ 0 ]
    paths = [ str( p ) for p, _m in files ]
    for mp3 in audio.values(): assert mp3 in paths                      # every language mp3
    assert str( source ) in paths                                       # RESOLVED source path
    assert "io/dr/report.md" not in paths
    assert not any( p in paths for p in script.values() )               # script flag is off
    assert { str( p ): m for p, m in files }[ next( iter( audio.values() ) ) ] == "audio/mpeg"
    assert job.artifacts[ "drive_folder_link" ] == FOLDER_LINK          # the done card field
    assert FOLDER_LINK in job.artifacts[ "abstract" ]


def test_pg_real_run_publishes_mp3s_and_resolved_source( fake_publisher, tmp_path ):
    root = tmp_path / "proj"
    source, audio, script = _make_files( root, [ "en", "es-MX" ] )
    job = _pg_job( target_languages=[ "en", "es-MX" ] )                 # RELATIVE research_path on purpose
    with patch.dict( sys.modules, _pg_modules( audio, script ) ), \
         patch.object( PodcastConfig, "from_config", side_effect=_config_with_publishing_on ), \
         patch( "cosa.utils.util.get_project_root", return_value=str( root ) ):
        asyncio.run( job._execute() )
    _assert_published( fake_publisher, job, source, audio, script )


def test_dr_real_run_publishes_mp3s_and_resolved_source( fake_publisher, tmp_path ):
    root = tmp_path / "proj"
    source, audio, script = _make_files( root, [ "en", "es-MX" ] )
    job   = _dr_job( target_languages=[ "en", "es-MX" ] )
    agent = MagicMock()
    agent.run_async = AsyncMock( return_value=_dr_result( source, audio, script ) )
    with patch.dict( sys.modules, _dr_modules() ), \
         patch.object( DeepResearchToPodcastJob, "_make_agent", return_value=agent ), \
         patch.object( PodcastConfig, "from_config", side_effect=_config_with_publishing_on ), \
         patch( "cosa.utils.util.get_project_root", return_value=str( root ) ):
        asyncio.run( job._execute() )
    _assert_published( fake_publisher, job, source, audio, script )
