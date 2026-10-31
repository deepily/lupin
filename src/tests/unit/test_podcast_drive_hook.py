"""
Unit tests for the shared podcast Drive hook, and for both podcast jobs' use of it.

No real Google call is made: the hook's publisher factory is replaced with a fake that records
what it was asked to upload.
"""

import contextlib
import os
import pathlib
import re
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cosa.agents.podcast_generator import drive_hook
from cosa.agents.podcast_generator.config import PodcastConfig


def _config( **overrides ):
    config = PodcastConfig()
    config.publish_to_google_drive = True
    for k, v in overrides.items(): setattr( config, k, v )
    return config


class FakePublisher:
    """Records publish_job() calls; `failures` maps a file name to its error text."""

    def __init__( self, failures=None, raises=None ):
        self.calls    = []
        self.failures = failures or {}
        self.raises   = raises

    def publish_job( self, job_folder_name, files ):
        self.calls.append( ( job_folder_name, files ) )
        if self.raises: raise self.raises
        return {
            "folder_id"   : "FID",
            "folder_link" : "https://drive.example/folders/FID",
            "files"       : [
                { "path": p, "file_id": None if os.path.basename( p ) in self.failures else "f1",
                  "web_view_link": None if os.path.basename( p ) in self.failures else f"https://drive.example/{os.path.basename( p )}",
                  "error": self.failures.get( os.path.basename( p ) ) }
                for p, _ in files
            ],
        }


@pytest.fixture
def fake( monkeypatch ):
    publisher = FakePublisher()
    monkeypatch.setattr( drive_hook, "_make_publisher", lambda config: publisher )
    return publisher


@pytest.fixture
def files( tmp_path ):
    paths = {}
    for name in [ "en.mp3", "es.mp3", "en-script.md", "es-script.md", "source.md" ]:
        paths[ name ] = str( tmp_path / name )
        open( paths[ name ], "w" ).write( "x" )
    return paths


def _publish( files, config, source="source.md" ):
    return drive_hook.publish_podcast_to_drive(
        { "en": files[ "en.mp3" ], "es-MX": files[ "es.mp3" ] },
        { "en": files[ "en-script.md" ], "es-MX": files[ "es-script.md" ] },
        files[ source ] if source else None, "2026-job", config )


class TestFlagOff:

    @pytest.mark.asyncio
    async def test_flag_off_returns_empty_and_never_builds_a_publisher( self, files, monkeypatch ):
        def boom( config ): raise AssertionError( "built a publisher with the flag off" )
        monkeypatch.setattr( drive_hook, "_make_publisher", boom )
        got = await _publish( files, _config( publish_to_google_drive=False ) )
        assert got == { "language_links": {}, "extra_lines": [], "folder_link": None }

    @pytest.mark.asyncio
    async def test_flag_off_leaves_the_drive_publisher_module_unimported( self, files, monkeypatch ):
        monkeypatch.delitem( sys.modules, "cosa.utils.drive_publisher", raising=False )
        await _publish( files, _config( publish_to_google_drive=False ) )
        assert "cosa.utils.drive_publisher" not in sys.modules

    def test_flag_off_imports_no_google_module_in_a_clean_process( self, tmp_path ):
        """A fresh interpreter: import the hook, run it with the flag off, list what got imported."""
        code = (
            "import asyncio, sys\n"
            "sys.path.insert( 0, sys.argv[ 1 ] )\n"
            "from cosa.agents.podcast_generator import drive_hook\n"
            "from cosa.agents.podcast_generator.config import PodcastConfig\n"
            "c = PodcastConfig()\n"
            "assert c.publish_to_google_drive is False\n"
            "r = asyncio.run( drive_hook.publish_podcast_to_drive( {'en': '/x.mp3'}, {}, '/s.md', 'job', c ) )\n"
            "assert r['folder_link'] is None\n"
            "bad = [m for m in sys.modules if m.startswith( ('googleapiclient', 'google_auth_oauthlib', 'cosa.utils.drive_publisher') )]\n"
            "print( 'LEAKED', bad ) if bad else print( 'CLEAN' )\n"
        )
        src = str( pathlib.Path( drive_hook.__file__ ).parents[ 3 ] )
        out = subprocess.run( [ sys.executable, "-I", "-c", code, src ], capture_output=True, text=True, env=os.environ, cwd=str( tmp_path ) )
        assert out.stdout.strip().endswith( "CLEAN" ), out.stdout + out.stderr


class TestSuccess:

    @pytest.mark.asyncio
    async def test_uploads_mp3s_then_source_with_their_mime_types( self, files, fake ):
        await _publish( files, _config() )
        assert fake.calls == [ ( "2026-job", [
            ( files[ "en.mp3" ], "audio/mpeg" ), ( files[ "es.mp3" ], "audio/mpeg" ), ( files[ "source.md" ], "text/markdown" ) ] ) ]

    @pytest.mark.asyncio
    async def test_returns_a_link_per_language_and_the_folder_line( self, files, fake ):
        got = await _publish( files, _config() )
        assert got[ "language_links" ] == { "en": "https://drive.example/en.mp3", "es-MX": "https://drive.example/es.mp3" }
        assert got[ "folder_link" ] == "https://drive.example/folders/FID"
        assert got[ "extra_lines" ] == [ "**Drive folder**: [☁️ Open](https://drive.example/folders/FID)" ]

    @pytest.mark.asyncio
    async def test_scripts_are_uploaded_only_when_their_flag_is_on( self, files, fake ):
        await _publish( files, _config( drive_upload_script=True ) )
        uploaded = [ os.path.basename( p ) for p, _ in fake.calls[ 0 ][ 1 ] ]
        assert uploaded == [ "en.mp3", "es.mp3", "en-script.md", "es-script.md", "source.md" ]
        assert dict( fake.calls[ 0 ][ 1 ] )[ files[ "en-script.md" ] ] == "text/markdown"

    @pytest.mark.asyncio
    async def test_source_document_is_skipped_when_its_flag_is_off( self, files, fake ):
        await _publish( files, _config( drive_upload_source_document=False ) )
        assert files[ "source.md" ] not in [ p for p, _ in fake.calls[ 0 ][ 1 ] ]

    @pytest.mark.asyncio
    async def test_source_document_is_skipped_when_missing_or_none( self, files, fake, tmp_path ):
        files[ "ghost" ] = str( tmp_path / "ghost.md" )
        await _publish( files, _config(), source="ghost" )
        await _publish( files, _config(), source=None )
        for _, sent in fake.calls: assert [ os.path.basename( p ) for p, _ in sent ] == [ "en.mp3", "es.mp3" ]

    @pytest.mark.asyncio
    async def test_unknown_source_type_goes_up_as_octet_stream( self, files, fake, tmp_path ):
        files[ "blob" ] = str( tmp_path / "source.zzzunknown" )
        open( files[ "blob" ], "w" ).write( "x" )
        await _publish( files, _config(), source="blob" )
        assert fake.calls[ 0 ][ 1 ][ -1 ] == ( files[ "blob" ], "application/octet-stream" )

    @pytest.mark.asyncio
    async def test_a_language_without_audio_is_not_uploaded( self, files, fake ):
        await drive_hook.publish_podcast_to_drive( { "en": files[ "en.mp3" ], "es-MX": None }, {}, None, "j", _config() )
        assert [ p for p, _ in fake.calls[ 0 ][ 1 ] ] == [ files[ "en.mp3" ] ]

    @pytest.mark.asyncio
    async def test_upload_runs_off_the_event_loop_thread( self, files, monkeypatch ):
        import threading
        seen = []
        class Spy( FakePublisher ):
            def publish_job( self, name, f ):
                seen.append( threading.current_thread() )
                return super().publish_job( name, f )
        monkeypatch.setattr( drive_hook, "_make_publisher", lambda config: Spy() )
        await _publish( files, _config() )
        assert seen[ 0 ] is not threading.current_thread()


class TestFailure:

    @pytest.mark.asyncio
    async def test_one_failed_file_keeps_the_others_and_adds_one_failure_line( self, files, monkeypatch ):
        monkeypatch.setattr( drive_hook, "_make_publisher", lambda c: FakePublisher( failures={ "es.mp3": "upload es.mp3: quota exceeded" } ) )
        got = await _publish( files, _config() )
        assert list( got[ "language_links" ] ) == [ "en" ]
        assert got[ "extra_lines" ][ 1 ] == "**Drive**: upload failed (es.mp3: upload es.mp3: quota exceeded)"
        assert got[ "extra_lines" ][ 0 ].startswith( "**Drive folder**" )

    @pytest.mark.asyncio
    @pytest.mark.parametrize( "error", [ ValueError( "bad token json" ), OSError( "disk gone" ), RuntimeError( "boom" ) ] )
    async def test_any_exception_from_the_publisher_becomes_one_failure_line( self, files, monkeypatch, error ):
        monkeypatch.setattr( drive_hook, "_make_publisher", lambda c: FakePublisher( raises=error ) )
        got = await _publish( files, _config() )
        assert got == { "language_links": {}, "folder_link": None,
                        "extra_lines": [ f"**Drive**: upload failed ({type( error ).__name__}: {error})" ] }

    @pytest.mark.asyncio
    async def test_an_exception_while_building_the_publisher_is_also_contained( self, files, monkeypatch ):
        def broken( config ): raise OSError( "token unreadable" )
        monkeypatch.setattr( drive_hook, "_make_publisher", broken )
        got = await _publish( files, _config() )
        assert got[ "extra_lines" ] == [ "**Drive**: upload failed (OSError: token unreadable)" ]


class TestBoundary:
    """Config loading, path resolving and folder naming sit inside the hook's catch-all."""

    @pytest.mark.asyncio
    async def test_without_a_config_it_loads_one_and_names_the_folder_from_the_resolved_source( self, files, fake, monkeypatch ):
        monkeypatch.setattr( drive_hook.cu, "get_project_root", lambda: os.path.dirname( files[ "source.md" ] ) )
        monkeypatch.setattr( drive_hook, "_load_config", lambda: _config() )
        got = await drive_hook.publish_podcast_to_drive( { "en": files[ "en.mp3" ] }, {}, "source.md" )
        folder, sent = fake.calls[ 0 ]
        assert re.fullmatch( r"\d{4}-\d{2}-\d{2}-\d{6}-source", folder )
        assert ( files[ "source.md" ], "text/markdown" ) in sent  # the relative name was resolved against the project root
        assert got[ "folder_link" ] is not None

    @pytest.mark.asyncio
    async def test_no_source_and_no_folder_name_falls_back_to_the_word_podcast( self, files, fake ):
        await drive_hook.publish_podcast_to_drive( { "en": files[ "en.mp3" ] }, {}, None, config=_config() )
        assert fake.calls[ 0 ][ 0 ].endswith( "-podcast" )

    @pytest.mark.asyncio
    async def test_a_given_folder_name_is_used_as_is( self, files, fake ):
        await drive_hook.publish_podcast_to_drive( { "en": files[ "en.mp3" ] }, {}, None, "mine", _config() )
        assert fake.calls[ 0 ][ 0 ] == "mine"

    @pytest.mark.asyncio
    async def test_a_config_that_cannot_load_becomes_the_failure_line( self, files, monkeypatch ):
        def broken(): raise ValueError( "ini unreadable" )
        monkeypatch.setattr( drive_hook, "_load_config", broken )
        got = await drive_hook.publish_podcast_to_drive( { "en": files[ "en.mp3" ] }, {}, "source.md" )
        assert got == { "language_links": {}, "folder_link": None, "extra_lines": [ "**Drive**: upload failed (ValueError: ini unreadable)" ] }

    def test_load_config_reads_the_real_ini( self ):
        assert drive_hook._load_config().publish_to_google_drive is False


class TestHelpers:

    def test_job_folder_name_is_timestamp_then_clean_topic( self ):
        name = drive_hook.make_job_folder_name( "/io/deep-research/u@x.com/2026.01.26 Quantum: Topic!.md" )
        assert re.fullmatch( r"\d{4}-\d{2}-\d{2}-\d{6}-2026.01.26-Quantum-Topic", name ), name
        assert "/" not in name

    @pytest.mark.parametrize( "given, expected", [
        ( None, None ), ( "", None ), ( "/abs/x.md", "/abs/x.md" ), ( "io/x.md", "/var/lupin/io/x.md" ) ] )
    def test_resolve_source_path( self, monkeypatch, given, expected ):
        monkeypatch.setattr( drive_hook.cu, "get_project_root", lambda: "/var/lupin" )
        assert drive_hook.resolve_source_path( given ) == expected

    def test_real_publisher_gets_the_resolved_token_path_and_folder_name( self, monkeypatch ):
        monkeypatch.setattr( drive_hook.cu, "get_project_root", lambda: "/var/lupin" )
        made = []
        monkeypatch.setattr( "cosa.utils.drive_publisher.DrivePublisher", lambda token, folder: made.append( ( token, folder ) ) or "PUB" )
        assert drive_hook._make_publisher( _config( drive_folder_name="My Pods" ) ) == "PUB"
        assert made == [ ( "/var/lupin/src/conf/keys/google-drive-oauth-token.json", "My Pods" ) ]


def _typed_get( wanted ):
    """A ConfigurationManager.get stand-in: the wanted value, else the typed default."""
    def get( key, default=None, silent=True, return_type="string" ):
        if key in wanted: return wanted[ key ]
        if default is None: return None
        converters = { "boolean": lambda v: str( v ).lower() == "true", "int": int, "float": float }
        return converters.get( return_type, str )( default )
    return get


_DRIVE_FIELDS = ( "publish_to_google_drive", "drive_folder_name", "drive_upload_script", "drive_upload_source_document", "drive_token_path" )


class TestConfigKeys:

    def test_dataclass_defaults( self ):
        c = PodcastConfig()
        assert [ getattr( c, f ) for f in _DRIVE_FIELDS ] == [ False, "Lupin Podcasts", False, True, "/src/conf/keys/google-drive-oauth-token.json" ]

    def test_from_config_falls_back_to_the_defaults_when_the_keys_are_absent( self ):
        mgr = MagicMock()
        mgr.get.side_effect = _typed_get( {} )
        c = PodcastConfig.from_config( mgr )
        assert [ getattr( c, f ) for f in _DRIVE_FIELDS ] == [ False, "Lupin Podcasts", False, True, "/src/conf/keys/google-drive-oauth-token.json" ]

    def test_from_config_reads_the_five_ini_names( self ):
        wanted = { "podcast publish to google drive": True, "podcast drive folder name": "F", "podcast drive upload script": True,
                   "podcast drive upload source document": False, "podcast drive token path": "/t.json" }
        mgr = MagicMock()
        mgr.get.side_effect = _typed_get( wanted )
        c = PodcastConfig.from_config( mgr )
        assert [ getattr( c, f ) for f in _DRIVE_FIELDS ] == [ True, "F", True, False, "/t.json" ]
        assert set( wanted ) <= { call.args[ 0 ] for call in mgr.get.call_args_list }

    def test_the_shipped_ini_carries_the_five_keys_with_the_documented_defaults_and_explainers( self ):
        """The real lupin-app.ini and its splainer, read through the real ConfigurationManager."""
        from cosa.config.configuration_manager import ConfigurationManager
        c = PodcastConfig.from_config( ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ) )
        assert [ getattr( c, f ) for f in _DRIVE_FIELDS ] == [ False, "Lupin Podcasts", False, True, "/src/conf/keys/google-drive-oauth-token.json" ]
        root = os.environ[ "LUPIN_ROOT" ] + "/src/conf/"
        for key in [ "podcast publish to google drive", "podcast drive folder name", "podcast drive upload script",
                     "podcast drive upload source document", "podcast drive token path" ]:
            for ini in [ "lupin-app.ini", "lupin-app-splainer.ini" ]:
                assert re.search( rf"^{re.escape( key )}\s*=", open( root + ini ).read(), re.M ), f"{key} missing from {ini}"


# ── both jobs call the shared hook ─────────────────────────────────────────────

def _hook_result( **kw ):
    return { "language_links": {}, "extra_lines": [], "folder_link": None, **kw }


def _pg_job( research_path="io/deep-research/u@x.com/research.md" ):
    from cosa.agents.podcast_generator.job import PodcastGeneratorJob
    return PodcastGeneratorJob( research_path=research_path, user_id="u", user_email="u@x.com", session_id="s", target_languages=[ "en" ] )


def _pg_agent():
    script = MagicMock()
    script.get_segment_count.return_value = 2
    script.estimated_duration_minutes     = 1.0
    agent = MagicMock()
    agent.do_all_async = AsyncMock( return_value=script )
    agent.podcast_id   = "pod"
    agent._api_client  = None
    agent._podcast_state = { "final_audio_path": "/var/lupin/io/podcasts/u/en.mp3", "final_script_path": "/var/lupin/io/podcasts/u/en.md" }
    return agent


async def _run_pg( job, hook ):
    with patch( "cosa.agents.podcast_generator.voice_io.notify", new_callable=AsyncMock ) as notify, \
         patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ), \
         patch( "cosa.agents.podcast_generator.voice_io.clear_job_id" ), \
         patch( "cosa.agents.podcast_generator.cosa_interface" ), \
         patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", return_value=_pg_agent() ), \
         patch( "cosa.agents.podcast_generator.drive_hook.publish_podcast_to_drive", hook ), \
         patch( "cosa.agents.podcast_generator.config.PodcastConfig.from_config", return_value=PodcastConfig() ), \
         patch( "os.path.exists", return_value=True ):
        answer = await job._execute()
    abstract = next( c.kwargs[ "abstract" ] for c in notify.call_args_list if c.kwargs.get( "abstract" ) and "Podcast Activity Report" in c.kwargs[ "abstract" ] )
    return answer, abstract


class TestPodcastGeneratorJobUsesTheHook:

    @pytest.mark.asyncio
    async def test_calls_the_hook_with_its_own_resolved_source_path( self, monkeypatch ):
        """A relative research_path reaches the hook resolved to an absolute path (Maria's fix 1)."""
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: "/var/lupin" )
        hook = AsyncMock( return_value=_hook_result() )
        await _run_pg( _pg_job(), hook )
        audio, script, source = hook.call_args.args
        assert audio  == { "en": "/var/lupin/io/podcasts/u/en.mp3" }
        assert script == { "en": "/var/lupin/io/podcasts/u/en.md" }
        assert source == "/var/lupin/io/deep-research/u@x.com/research.md"
        assert isinstance( hook.call_args.kwargs[ "config" ], PodcastConfig )

    @pytest.mark.asyncio
    async def test_success_adds_links_folder_line_and_artifact( self, monkeypatch ):
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: "/var/lupin" )
        hook = AsyncMock( return_value=_hook_result( language_links={ "en": "https://d/en" }, folder_link="https://d/F",
                                                     extra_lines=[ "**Drive folder**: [☁️ Open](https://d/F)" ] ) )
        job = _pg_job()
        _, abstract = await _run_pg( job, hook )
        assert "[☁️ Drive](https://d/en)" in abstract
        assert "**Drive folder**: [☁️ Open](https://d/F)" in abstract
        assert job.artifacts[ "drive_folder_link" ] == "https://d/F"

    @pytest.mark.asyncio
    async def test_failure_line_shows_and_the_job_still_succeeds( self, monkeypatch ):
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: "/var/lupin" )
        hook = AsyncMock( return_value=_hook_result( extra_lines=[ "**Drive**: upload failed (OSError: x)" ] ) )
        job = _pg_job()
        answer, abstract = await _run_pg( job, hook )
        assert "**Drive**: upload failed (OSError: x)" in abstract
        assert answer.startswith( "Podcast complete!" ) and "drive_folder_link" not in job.artifacts

    @pytest.mark.asyncio
    async def test_dry_run_never_calls_the_hook( self ):
        from cosa.agents.podcast_generator.job import PodcastGeneratorJob
        job  = PodcastGeneratorJob( research_path="io/x.md", user_id="u", user_email="u@x.com", session_id="s", dry_run=True )
        hook = AsyncMock()
        with patch( "cosa.agents.podcast_generator.voice_io.notify", new_callable=AsyncMock ), \
             patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ), \
             patch( "cosa.agents.podcast_generator.voice_io.clear_job_id" ), \
             patch( "cosa.agents.podcast_generator.cosa_interface" ), \
             patch( "cosa.agents.podcast_generator.drive_hook.publish_podcast_to_drive", hook ), \
             patch( "asyncio.sleep", new_callable=AsyncMock ):
            await job._execute()
        hook.assert_not_called()


def _drp_job():
    from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
    return DeepResearchToPodcastJob( query="q", user_id="u", user_email="u@x.com", session_id="s", target_languages=[ "en" ] )


async def _run_drp( job, hook, research_path="io/deep-research/u@x.com/report.md" ):
    from cosa.agents.deep_research_to_podcast.state import PipelineState
    result = SimpleNamespace(
        state=PipelineState.COMPLETED, error=None, research_path=research_path, research_abstract="a",
        audio_path="/var/lupin/io/podcasts/u/en.mp3", script_path="/var/lupin/io/podcasts/u/en.md",
        pg_artifacts={ "audio_paths_by_language": { "en": "/var/lupin/io/podcasts/u/en.mp3" },
                       "script_paths_by_language": { "en": "/var/lupin/io/podcasts/u/en.md" } },
        dr_cost=1.0, pg_cost=1.0, total_cost=2.0 )
    agent = MagicMock()
    agent.run_async = AsyncMock( return_value=result )
    hook_patch = patch( "cosa.agents.podcast_generator.drive_hook.publish_podcast_to_drive", hook ) if hook is not None else contextlib.nullcontext()
    with patch( "cosa.agents.deep_research.voice_io.notify", new_callable=AsyncMock ) as notify, \
         patch( "cosa.agents.deep_research.voice_io.set_job_id" ), \
         patch( "cosa.agents.deep_research.voice_io.clear_job_id" ), \
         patch( "cosa.agents.deep_research.cosa_interface" ), \
         hook_patch, \
         patch.object( type( job ), "_make_agent", return_value=agent ):
        await job._execute()
    return next( c.kwargs[ "abstract" ] for c in notify.call_args_list if c.kwargs.get( "abstract" ) and "Research → Podcast Complete" in c.kwargs[ "abstract" ] )


class TestDeepResearchToPodcastJobUsesTheHook:

    @pytest.mark.asyncio
    async def test_a_config_error_in_the_real_hook_does_not_fail_the_job( self ):
        """No stub: the real hook runs and PodcastConfig.from_config raises."""
        job = _drp_job()
        with patch( "cosa.agents.podcast_generator.config.PodcastConfig.from_config", side_effect=ValueError( "ini unreadable" ) ):
            abstract = await _run_drp( job, None )
        assert "**Drive**: upload failed (ValueError: ini unreadable)" in abstract
        assert "Research → Podcast Complete" in abstract and "drive_folder_link" not in job.artifacts

    @pytest.mark.asyncio
    async def test_publishing_off_through_the_real_hook_adds_nothing( self ):
        job      = _drp_job()
        abstract = await _run_drp( job, None )
        assert "Drive" not in abstract and "drive_folder_link" not in job.artifacts

    @pytest.mark.asyncio
    async def test_calls_the_hook_with_the_research_report_path( self, monkeypatch ):
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: "/var/lupin" )
        hook = AsyncMock( return_value=_hook_result() )
        await _run_drp( _drp_job(), hook )
        audio, script, source = hook.call_args.args
        assert audio  == { "en": "/var/lupin/io/podcasts/u/en.mp3" }
        assert script == { "en": "/var/lupin/io/podcasts/u/en.md" }
        assert source == "io/deep-research/u@x.com/report.md"  # unresolved: the hook resolves it inside its boundary
        assert hook.call_args.kwargs == {}

    @pytest.mark.asyncio
    async def test_no_research_path_still_calls_the_hook_with_no_source( self, monkeypatch ):
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: "/var/lupin" )
        hook = AsyncMock( return_value=_hook_result() )
        await _run_drp( _drp_job(), hook, research_path=None )
        assert hook.call_args.args[ 2 ] is None

    @pytest.mark.asyncio
    async def test_success_adds_links_folder_line_and_artifact( self, monkeypatch ):
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: "/var/lupin" )
        hook = AsyncMock( return_value=_hook_result( language_links={ "en": "https://d/en" }, folder_link="https://d/F",
                                                     extra_lines=[ "**Drive folder**: [☁️ Open](https://d/F)" ] ) )
        job      = _drp_job()
        abstract = await _run_drp( job, hook )
        assert "[☁️ Drive](https://d/en)" in abstract
        assert "**Drive folder**: [☁️ Open](https://d/F)" in abstract
        assert job.artifacts[ "drive_folder_link" ] == "https://d/F"

    @pytest.mark.asyncio
    async def test_failure_line_shows_and_the_job_still_succeeds( self, monkeypatch ):
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: "/var/lupin" )
        hook     = AsyncMock( return_value=_hook_result( extra_lines=[ "**Drive**: upload failed (OSError: x)" ] ) )
        job      = _drp_job()
        abstract = await _run_drp( job, hook )
        assert "**Drive**: upload failed (OSError: x)" in abstract and "drive_folder_link" not in job.artifacts
