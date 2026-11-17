"""
Unit tests for the helpers the group F reuse follow-up folded duplicate code into.

Each helper replaced two or three inline copies. Each test pins the behaviour those copies shared.
The helpers cover the podcast links, the chained-job cards, the Deep Research report steps and the alert posts.

Venue: :7999-eligible. No server, no network, no model call.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import cosa.utils.hook_link_tick as hlt
from cosa.agents.deep_research import job as dr_job
from cosa.agents.deep_research_to_presentation.job import DeepResearchToPresentationJob
from cosa.agents.podcast_generator import play_links as pl

IO_BASE = "/proj/io/"


class TestPodcastLinkHelpers:

    @pytest.mark.parametrize( "path, expected", [
        ( None,                              None ),
        ( "",                                None ),
        ( "/proj/io/podcasts/u/a.mp3",       "podcasts/u/a.mp3" ),
        ( "io/podcasts/u/a.mp3",             "podcasts/u/a.mp3" ),
        ( "/io/podcasts/u/a.mp3",            "io/podcasts/u/a.mp3" ),
        ( "podcasts/u/a.mp3",                "podcasts/u/a.mp3" ),
    ] )
    def test_io_relative_takes_every_form_the_io_endpoint_takes( self, path, expected ):
        assert pl.io_relative( path, IO_BASE ) == expected

    def test_ordered_languages_puts_the_requested_ones_first_and_adds_extras_once( self ):
        got = pl.ordered_languages( [ "en", "fr", "es" ], { "es": "a", "de": "b" }, { "en": "s", "de": "t" } )
        assert got == [ "en", "es", "de" ]

    def test_language_card_lines_builds_one_line_per_language_with_links( self ):
        lines = pl.language_card_lines(
            [ "en", "xx", "zz" ], { "en": "English" },
            { "en": "/proj/io/podcasts/u/en.mp3", "xx": "/proj/io/podcasts/u/xx.mp3" },
            { "en": "/proj/io/podcasts/u/en.md" },
            "lupin/src/r.md", IO_BASE, { "en": "http://drive/en" }
        )
        assert len( lines ) == 2
        assert lines[ 0 ].startswith( "**English**: [📝 Script](" ) and "[▶️ Play Here](" in lines[ 0 ] and lines[ 0 ].endswith( " | [☁️ Drive](http://drive/en)" )
        assert lines[ 1 ].startswith( "**xx**: [▶️ Play Here](" ) and "script=" not in lines[ 1 ]

    def test_language_card_lines_skips_a_language_with_nothing_to_link( self ):
        assert pl.language_card_lines( [ "en" ], { }, { }, { }, None, IO_BASE, { } ) == [ ]


class _Job( DeepResearchToPresentationJob ):
    pass


def _job():
    return _Job( query="q", user_id="u", user_email="who@x.com", session_id="s" )


class TestChainedJobHelpers:

    def test_io_view_link_links_a_file_under_io_and_leaves_any_other_path_alone( self ):
        job = _job()
        with patch( "cosa.agents.agentic_job_base.cu.get_project_root", return_value="/proj" ):
            assert job._io_view_link( "/proj/io/deep-research/a b.md", "View" ) == "[View](/app/docs?path=deep-research/a%20b.md)"
            assert job._io_view_link( "/elsewhere/a.md", "View" ) == "/elsewhere/a.md"
            assert job._io_view_link( None, "View" ) is None

    def test_skipped_topic_names_and_line( self ):
        result = SimpleNamespace( dr_artifacts={ "skipped_topics": [ { "topic": "a" }, { "topic": "b" } ] } )
        names  = _job()._skipped_topic_names( result )
        assert names == [ "a", "b" ]
        assert _job()._skipped_topics_line( names ) == "**Skipped topics (2)**: a; b"
        assert _job()._skipped_topic_names( SimpleNamespace( dr_artifacts={ } ) ) == [ ]

    def test_dry_run_paths_and_research_store( self ):
        job = _job()
        assert job._dry_run_io_path( "podcasts", "x.mp3" ) == f"/io/podcasts/who@x.com/dry-run-{job.id_hash}/x.mp3"
        job._store_dry_run_research()
        assert job.research_path == f"/io/deep-research/who@x.com/dry-run-{job.id_hash}/report.md"
        assert job.artifacts[ "research_path" ] == job.research_path
        assert job.artifacts[ "research_abstract" ] == "Mock abstract from dry-run mode."

    def test_presentation_dry_run_results_keep_their_old_shape( self ):
        job      = _job()
        abstract = job._store_dry_run_results()
        base     = f"/io/presentations/who@x.com/dry-run-{job.id_hash}/"
        assert ( job.yaml_path, job.marp_path ) == ( base + "presentation.yaml", base + "presentation.md" )
        assert job.artifacts[ "slide_count" ] == 0 and f"**YAML**: {job.yaml_path} (mock" in abstract


class TestDeepResearchReportHelpers:

    @pytest.mark.parametrize( "configured, expected", [
        ( "io/dr",              "/proj/io/dr" ),
        ( "/io/dr",             "/proj/io/dr" ),
        ( "/proj/already/here", "/proj/already/here" ),
    ] )
    def test_resolve_output_settings_anchors_the_directory_under_the_project( self, configured, expected ):
        values = { "deep research storage backend": "gcs", "deep research gcs bucket": "b", "deep research output directory": configured }
        mgr    = MagicMock()
        mgr.get.side_effect = lambda key, default=None: values[ key ]
        with patch( "cosa.agents.deep_research.job.cu.get_project_root", return_value="/proj" ):
            assert dr_job.resolve_output_settings( mgr ) == ( "gcs", "b", expected )

    @pytest.mark.parametrize( "gist, expected", [
        ( "  Mixed Case Name ", "mixed case name" ),
        ( "   ",                "general research query" ),
        ( None,                 "general research query" ),
    ] )
    def test_derive_session_name_lowercases_trims_and_falls_back( self, gist, expected ):
        with patch( "cosa.memory.gister.Gister" ) as gister:
            gister.return_value.get_gist.return_value = gist
            name, topic = dr_job.derive_session_name( "query" )
        assert name == expected and topic == expected.replace( " ", "-" )

    def test_abstract_and_save_report_passes_the_same_arguments_to_both_calls( self ):
        with patch( "cosa.agents.deep_research.cli.generate_abstract_for_cli", new=AsyncMock( return_value="abs" ) ) as gen, \
             patch( "cosa.agents.deep_research.cli.save_report_with_frontmatter", return_value="/p/report.md" ) as save:
            got = asyncio.run( dr_job.abstract_and_save_report( "rep", "q", "cfg", "tracker", "sid", "topic", ( "local", None, "/out" ), "who@x.com", debug=True ) )
        assert got == ( "abs", "/p/report.md" )
        assert gen.call_args.kwargs == { "report": "rep", "config": "cfg", "cost_tracker": "tracker", "debug": True }
        assert save.call_args.kwargs[ "abstract" ] == "abs" and save.call_args.kwargs[ "output_dir" ] == "/out"
        assert save.call_args.kwargs[ "session_id" ] == "sid" and save.call_args.kwargs[ "storage_backend" ] == "local"


class TestNotifyHelpers:

    def test_notify_route_resolves_base_key_and_target( self ):
        got = hlt.notify_route( { "B": "http://h:1/" }, "B", api_key=lambda: "k", target_of=lambda e: "rick@x" )
        assert got == ( "http://h:1", "k", "rick@x" )
        assert hlt.notify_route( { }, "B", "http://d/", api_key=lambda: "k", target_of=lambda e: "r" )[ 0 ] == "http://d"

    def test_notify_route_refuses_a_missing_recipient( self ):
        with pytest.raises( ValueError, match = "no notification recipient" ):
            hlt.notify_route( { }, "B", api_key=lambda: "k", target_of=lambda e: None )

    def test_notify_route_falls_back_to_the_live_lookups( self, monkeypatch ):
        monkeypatch.setattr( hlt, "_api_key", lambda: "live-key" )
        monkeypatch.setattr( hlt, "_notify_target", lambda environ: "live@x" )
        assert hlt.notify_route( { }, "B" ) == ( hlt.DEFAULT_API_BASE, "live-key", "live@x" )

    def test_send_notify_posts_the_alert_fields_with_a_fresh_idempotency_key( self ):
        seen = []
        def query( base, key, path, params ): seen.append( ( base, key, path, params ) ); return 200, "ok"
        assert hlt.send_notify( "http://h", "k", "who", "msg", "abs", "sender", query=query ) == ( 200, "ok" )
        hlt.send_notify( "http://h", "k", "who", "msg", "abs", "sender", priority="low", kind="progress", query=query )
        first, second = seen[ 0 ][ 3 ], seen[ 1 ][ 3 ]
        assert seen[ 0 ][ :3 ] == ( "http://h", "k", "/api/notify" )
        assert ( first[ "type" ], first[ "priority" ], first[ "sender_id" ], first[ "target_user" ] ) == ( "alert", "high", "sender", "who" )
        assert ( second[ "type" ], second[ "priority" ] ) == ( "progress", "low" )
        assert first[ "idempotency_key" ] != second[ "idempotency_key" ]

