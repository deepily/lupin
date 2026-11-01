"""
Unit tests for the shared Play Here link builder and its use by both podcast jobs.

The script and the mp3 carry different time stamps, so the job passes the paths.
"""

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlparse

import pytest

from cosa.agents.podcast_generator import play_links as pl


class TestCleanTitle:

    @pytest.mark.parametrize( "heading, expected", [
        ( "Podcast: Grading Your Own Exam: Construct Validity", "Grading Your Own Exam: Construct Validity" ),
        ( "  podcast :   Lower Case  ",                         "Lower Case" ),
        ( "No Prefix Here",                                     "No Prefix Here" ),
        ( "Podcast:   ",                                        None ),
        ( None,                                                 None ),
    ] )
    def test_strips_the_label_and_spaces( self, heading, expected ):
        assert pl.clean_title( heading ) == expected


class TestReadScriptTitle:

    def test_reads_the_first_heading_without_the_label( self, tmp_path ):
        script = tmp_path / "2026.11.01-014724-x-script.md"
        script.write_text( "# Podcast: Grading Your Own Exam\n## Generated: 2026-11-01T01:47:24\n\n# Podcast: Second\n", encoding="utf-8" )
        assert pl.read_script_title( str( script ) ) == "Grading Your Own Exam"

    def test_no_heading_gives_none( self, tmp_path ):
        script = tmp_path / "s.md"
        script.write_text( "## only a second-level heading\n", encoding="utf-8" )
        assert pl.read_script_title( str( script ) ) is None

    def test_missing_file_gives_none( self, tmp_path ):
        assert pl.read_script_title( str( tmp_path / "absent.md" ) ) is None

    def test_empty_path_gives_none( self ):
        assert pl.read_script_title( None ) is None and pl.read_script_title( "" ) is None


class TestTitleFromScriptText:

    def test_the_first_heading_without_its_label( self ):
        assert pl.title_from_script_text( "intro\n# Podcast: The Empty Net\n## Generated: x\n" ) == "The Empty Net"

    def test_no_heading_gives_none( self ):
        assert pl.title_from_script_text( "## only a second-level heading" ) is None


class TestTitleFromFolderName:

    @pytest.mark.parametrize( "name, expected", [
        ( "2026-11-01-184006-the-empty-net",                                    "The Empty Net" ),
        ( "2026-11-01-014849-grading_your-own-exam",                            "Grading Your Own Exam" ),
        ( "2026-11-01-190015-2026.10.31-google-drive-sign-in-explainer",        "Google Drive Sign In Explainer" ),
        ( "2026-11-01-190015-2026.10.31-014724-google-drive-sign-in-explainer", "Google Drive Sign In Explainer" ),
        ( "2026.11.01-184006-the-empty-net",                                    "The Empty Net" ),
        ( "20261101-a1b2c3d4-the-empty-net",                                    "The Empty Net" ),
        ( "2026-11-01-184006-the-empty-net-a1b2c3d4",                           "The Empty Net" ),
        ( "no-stamp-here",                                                      "No Stamp Here" ),
        ( "2026 outlook",                                                       "2026 Outlook" ),
        ( "decade-review",                                                      "Decade Review" ),
        ( "2026-11-01-184006-",                                                 "2026-11-01-184006-" ),
    ] )
    def test_every_leading_date_time_and_serial_is_removed( self, name, expected ):
        assert pl.title_from_folder_name( name ) == expected


class TestSourceRef:

    def test_absolute_under_io( self ):
        assert pl.source_ref( "/var/lupin/io/deep-research/u/r.md", "/var/lupin" ) == "io/deep-research/u/r.md"

    def test_relative_io( self ):
        assert pl.source_ref( "io/deep-research/u/r.md", "/var/lupin" ) == "io/deep-research/u/r.md"

    def test_absolute_elsewhere_in_the_project_is_doc_viewer_form( self ):
        assert pl.source_ref( "/var/lupin/src/rnd/v0.2.2/plan.md", "/var/lupin" ) == "lupin/src/rnd/v0.2.2/plan.md"

    def test_relative_elsewhere_in_the_project_is_doc_viewer_form( self ):
        assert pl.source_ref( "src/rnd/plan.md", "/var/lupin" ) == "lupin/src/rnd/plan.md"

    def test_absolute_outside_the_project_is_none( self ):
        assert pl.source_ref( "/home/x/notes.md", "/var/lupin" ) is None

    def test_empty_is_none( self ):
        assert pl.source_ref( None, "/var/lupin" ) is None and pl.source_ref( "", "/var/lupin" ) is None


class TestAudioTriplet:

    def _query( self, markdown, label ):
        url = next( p for p in markdown.split( " | " ) if label in p ).split( "](" )[ 1 ].rstrip( ")" )
        return urlparse( url ), parse_qs( urlparse( url ).query )

    def test_carries_script_source_and_title( self ):
        md = pl.audio_triplet( "podcasts/u/a.mp3", "podcasts/u/b-script.md", "deep-research/u/r.md", "Grading Your Own Exam: Construct Validity" )
        parsed, q = self._query( md, "Play Here" )
        assert parsed.path == "/app/audio"
        assert q == { "path": [ "podcasts/u/a.mp3" ], "script": [ "podcasts/u/b-script.md" ], "source": [ "deep-research/u/r.md" ],
                      "title": [ "Grading Your Own Exam: Construct Validity" ], "embed": [ "1" ] }

    def test_listen_is_the_same_url_without_embed( self ):
        md = pl.audio_triplet( "podcasts/u/a.mp3", "s.md", "r.md", "T" )
        _, play   = self._query( md, "Play Here" )
        _, listen = self._query( md, "Listen" )
        assert "embed" not in listen and { k: v for k, v in play.items() if k != "embed" } == listen

    def test_absent_values_are_left_out_not_written_empty( self ):
        md = pl.audio_triplet( "podcasts/u/a.mp3" )
        _, q = self._query( md, "Play Here" )
        assert q == { "path": [ "podcasts/u/a.mp3" ], "embed": [ "1" ] }
        assert "script=" not in md and "source=" not in md and "title=" not in md

    def test_download_link_is_unchanged( self ):
        assert "[⬇️ Download](/api/io/file?path=podcasts/u/a.mp3&download=true)" in pl.audio_triplet( "podcasts/u/a.mp3", "s", "r", "T" )

    def test_title_with_ampersand_and_hash_survives_the_round_trip( self ):
        _, q = self._query( pl.audio_triplet( "a.mp3", title="R&D #1 100%" ), "Play Here" )
        assert q[ "title" ] == [ "R&D #1 100%" ]


def _pg_job():
    from cosa.agents.podcast_generator.job import PodcastGeneratorJob
    return PodcastGeneratorJob( research_path="io/deep-research/u/research.md", user_id="u", user_email="pl@test.com",
                                session_id="s", target_languages=[ "en" ], debug=False )


class TestPodcastGeneratorJobCard:

    @pytest.mark.asyncio
    async def test_real_script_title_and_both_paths_reach_the_card( self, tmp_path, monkeypatch ):
        job = _pg_job()
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: str( tmp_path ) )
        pdir = tmp_path / "io" / "podcasts" / "u"
        pdir.mkdir( parents=True )
        # The time stamps differ, so the job must pass the paths and cannot pair them by name.
        ( pdir / "2026.11.01-014724-grading-script.md" ).write_text( "# Podcast: Grading Your Own Exam\n", encoding="utf-8" )
        research = tmp_path / "io" / "deep-research" / "u" / "research.md"
        research.parent.mkdir( parents=True )
        research.write_text( "# r\n", encoding="utf-8" )

        job.research_path = str( research )
        script = MagicMock()
        script.get_segment_count.return_value = 1
        script.estimated_duration_minutes = 1.0
        agent = MagicMock()
        agent.do_all_async = AsyncMock( return_value=script )
        agent.podcast_id = "p"
        agent._api_client = None
        agent._podcast_state = { "final_audio_path": "io/podcasts/u/2026.11.01-014849-grading.mp3",
                                 "final_script_path": "io/podcasts/u/2026.11.01-014724-grading-script.md" }
        with patch( "cosa.agents.podcast_generator.voice_io.notify", new_callable=AsyncMock ) as notify, \
             patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ), \
             patch( "cosa.agents.podcast_generator.voice_io.clear_job_id" ), \
             patch( "cosa.agents.podcast_generator.cosa_interface" ), \
             patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", return_value=agent ), \
             patch( "os.path.exists", return_value=True ):
            await job._execute()
        abstract = next( c.kwargs[ "abstract" ] for c in notify.call_args_list if c.kwargs.get( "abstract" ) and "Podcast Activity Report" in c.kwargs[ "abstract" ] )
        assert "script=podcasts/u/2026.11.01-014724-grading-script.md" in abstract
        assert "source=io/deep-research/u/research.md" in abstract
        assert "title=Grading%20Your%20Own%20Exam" in abstract

    @pytest.mark.asyncio
    async def test_unreadable_script_and_outside_source_leave_those_values_out( self, tmp_path, monkeypatch ):
        job = _pg_job()
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: str( tmp_path ) )
        job.research_path = "/elsewhere/research.md"   # outside the project: no source value
        script = MagicMock()
        script.get_segment_count.return_value = 1
        script.estimated_duration_minutes = 1.0
        agent = MagicMock()
        agent.do_all_async = AsyncMock( return_value=script )
        agent.podcast_id = "p"
        agent._api_client = None
        agent._podcast_state = { "final_audio_path": "io/podcasts/u/a.mp3", "final_script_path": "io/podcasts/u/absent-script.md" }
        with patch( "cosa.agents.podcast_generator.voice_io.notify", new_callable=AsyncMock ) as notify, \
             patch( "cosa.agents.podcast_generator.voice_io.reconfigure" ), \
             patch( "cosa.agents.podcast_generator.voice_io.clear_job_id" ), \
             patch( "cosa.agents.podcast_generator.cosa_interface" ), \
             patch( "cosa.agents.podcast_generator.orchestrator.PodcastOrchestratorAgent", return_value=agent ), \
             patch( "os.path.exists", return_value=True ):
            await job._execute()
        abstract = next( c.kwargs[ "abstract" ] for c in notify.call_args_list if c.kwargs.get( "abstract" ) and "Podcast Activity Report" in c.kwargs[ "abstract" ] )
        assert "/app/audio?path=podcasts/u/a.mp3&script=podcasts/u/absent-script.md&embed=1" in abstract
        assert "source=" not in abstract and "title=" not in abstract


def _drp_job():
    from cosa.agents.deep_research_to_podcast.job import DeepResearchToPodcastJob
    return DeepResearchToPodcastJob( query="q", user_id="u", user_email="u@x.com", session_id="s", target_languages=[ "en" ] )


class TestDeepResearchToPodcastJobCard:

    @pytest.mark.asyncio
    async def test_title_script_and_source_reach_the_card( self, tmp_path, monkeypatch ):
        job = _drp_job()
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: str( tmp_path ) )
        pdir = tmp_path / "io" / "podcasts" / "u"
        pdir.mkdir( parents=True )
        ( pdir / "en-script.md" ).write_text( "# Podcast: The Empty Net\n", encoding="utf-8" )
        from cosa.agents.deep_research_to_podcast.state import PipelineState
        io = str( tmp_path ) + "/io/podcasts/u/"
        result = SimpleNamespace(
            state=PipelineState.COMPLETED, error=None, research_path="io/deep-research/u/report.md", research_abstract="a",
            audio_path=io + "en.mp3", script_path=io + "en-script.md",
            pg_artifacts={ "audio_paths_by_language": { "en": io + "en.mp3" }, "script_paths_by_language": { "en": io + "en-script.md" } },
            dr_cost=1.0, pg_cost=1.0, total_cost=2.0 )
        agent = MagicMock()
        agent.run_async = AsyncMock( return_value=result )
        with patch( "cosa.agents.deep_research.voice_io.notify", new_callable=AsyncMock ) as notify, \
             patch( "cosa.agents.deep_research.voice_io.set_job_id" ), \
             patch( "cosa.agents.deep_research.voice_io.clear_job_id" ), \
             patch( "cosa.agents.deep_research.cosa_interface" ), \
             patch.object( type( job ), "_make_agent", return_value=agent ):
            await job._execute()
        abstract = next( c.kwargs[ "abstract" ] for c in notify.call_args_list if c.kwargs.get( "abstract" ) and "Research → Podcast Complete" in c.kwargs[ "abstract" ] )
        assert "path=podcasts/u/en.mp3&script=podcasts/u/en-script.md&source=io/deep-research/u/report.md&title=The%20Empty%20Net&embed=1" in abstract
        assert "[📝 Script](/app/docs?path=lupin/io/podcasts/u/en-script.md)" in abstract

    @pytest.mark.asyncio
    async def test_a_script_without_audio_still_gets_the_script_link( self, tmp_path, monkeypatch ):
        job = _drp_job()
        monkeypatch.setattr( "cosa.utils.util.get_project_root", lambda: str( tmp_path ) )
        from cosa.agents.deep_research_to_podcast.state import PipelineState
        io = str( tmp_path ) + "/io/podcasts/u/"
        result = SimpleNamespace(
            state=PipelineState.COMPLETED, error=None, research_path="io/deep-research/u/report.md", research_abstract="a",
            audio_path=None, script_path=io + "en-script.md",
            pg_artifacts={ "audio_paths_by_language": {}, "script_paths_by_language": { "en": io + "en-script.md" } },
            dr_cost=1.0, pg_cost=1.0, total_cost=2.0 )
        agent = MagicMock()
        agent.run_async = AsyncMock( return_value=result )
        with patch( "cosa.agents.deep_research.voice_io.notify", new_callable=AsyncMock ) as notify, \
             patch( "cosa.agents.deep_research.voice_io.set_job_id" ), \
             patch( "cosa.agents.deep_research.voice_io.clear_job_id" ), \
             patch( "cosa.agents.deep_research.cosa_interface" ), \
             patch.object( type( job ), "_make_agent", return_value=agent ):
            await job._execute()
        abstract = next( c.kwargs[ "abstract" ] for c in notify.call_args_list if c.kwargs.get( "abstract" ) and "Research → Podcast Complete" in c.kwargs[ "abstract" ] )
        assert "[📝 Script](/app/docs?path=lupin/io/podcasts/u/en-script.md)" in abstract and "Play Here" not in abstract


class TestDryRunCard:

    @pytest.mark.asyncio
    async def test_dry_run_card_keeps_the_plain_player_link( self ):
        job   = _pg_job()
        voice = MagicMock()
        voice.notify = AsyncMock()
        with patch( "asyncio.sleep", new_callable=AsyncMock ):
            await job._execute_dry_run( voice, MagicMock() )
        abstract = next( c.kwargs[ "abstract" ] for c in voice.notify.call_args_list if c.kwargs.get( "abstract" ) )
        assert "[▶️ Play Here](/app/audio?path=fixtures/podcast-dry-run/podcast-dry-run.mp3&embed=1)" in abstract


class TestScriptLink:

    def test_script_link_opens_the_doc_viewer_in_the_lupin_scope( self ):
        from cosa.agents.podcast_generator.play_links import script_link
        assert script_link( "podcasts/u@x.com/en-script.md" ) == "[📝 Script](/app/docs?path=lupin/io/podcasts/u%40x.com/en-script.md)"

    def test_script_link_without_a_script_is_none( self ):
        from cosa.agents.podcast_generator.play_links import script_link
        assert script_link( None ) is None
        assert script_link( "" ) is None
