#!/usr/bin/env python3
"""
Unit tests — `cosa.rest.agentic_job_factory` (comprehensive coverage).

This file covers:

    - the four private parser helpers (`_parse_optional_int`, `_parse_boolean`,
      `_parse_optional_boolean`, `_parse_optional_float`) across every arm,
    - every command branch of `create_agentic_job()`, with
      each concrete Job class boundary-mocked at its source module so NO heavy
      agent / LLM / network init runs and ZERO API spend occurs,
    - `resume_job()` across its full success/failure branch matrix.

Boundary-mock discipline: every `cosa.agents.*.job.<Job>` symbol is patched to
a `MagicMock` in `setUp`; the factory's call-time `from … import …` then binds
the mock, so constructing a job never touches real agent code. `resume_job`'s
`job_persistence` reads and its inner `create_agentic_job` call are patched too.

Run: PYTHONPATH=src:src/cosa/tests/unit/infrastructure \
     src/cosa/.venv/bin/python -m pytest \
     src/cosa/tests/unit/rest/test_agentic_job_factory.py -v
"""

import unittest
from unittest.mock import patch, MagicMock

import cosa.rest.agentic_job_factory as ajf
from   cosa.rest.agentic_job_factory import (
    create_agentic_job,
    resume_job,
    _parse_optional_int,
    _parse_boolean,
    _parse_optional_boolean,
    _parse_optional_float,
)


# ---------------------------------------------------------------------------
# Parser helpers — full branch matrix
# ---------------------------------------------------------------------------
class TestParseOptionalInt( unittest.TestCase ):
    """
    Exercises `_parse_optional_int`.

    Ensures:
        - valid numeric strings/ints parse
        - semantic-none / falsy values return the default
        - unparseable values fall through the except arm to the default
    """

    def test_valid_int_string( self ):
        self.assertEqual( _parse_optional_int( "42" ), 42 )

    def test_valid_int_passthrough( self ):
        self.assertEqual( _parse_optional_int( 7 ), 7 )

    def test_falsy_returns_default( self ):
        # empty / None / 0 are falsy → default
        self.assertIsNone( _parse_optional_int( "" ) )
        self.assertIsNone( _parse_optional_int( None ) )

    def test_semantic_none_returns_default( self ):
        self.assertIsNone( _parse_optional_int( "no limit" ) )

    def test_custom_default( self ):
        self.assertEqual( _parse_optional_int( "skip", default=99 ), 99 )

    def test_unparseable_hits_except_arm( self ):
        # non-numeric, non-semantic string → int() raises → except → default
        self.assertIsNone( _parse_optional_int( "abc" ) )
        self.assertEqual( _parse_optional_int( "abc", default=5 ), 5 )


class TestParseBoolean( unittest.TestCase ):
    """
    Exercises `_parse_boolean`.

    Ensures:
        - None returns the default (the `value is None` arm)
        - bool values pass through unchanged
        - truthy words map to True; everything else maps to False
    """

    def test_none_returns_default( self ):
        self.assertFalse( _parse_boolean( None ) )
        self.assertTrue( _parse_boolean( None, default=True ) )

    def test_bool_passthrough( self ):
        self.assertTrue( _parse_boolean( True ) )
        self.assertFalse( _parse_boolean( False ) )

    def test_truthy_words( self ):
        for w in ( "yes", "true", "1", "enable", "enabled", "  YES  " ):
            self.assertTrue( _parse_boolean( w ), w )

    def test_falsy_words( self ):
        for w in ( "no", "false", "0", "nope" ):
            self.assertFalse( _parse_boolean( w ), w )


class TestParseOptionalBoolean( unittest.TestCase ):
    """
    Exercises `_parse_optional_boolean` (tri-state True/False/None).

    Ensures:
        - None and semantic-none/unknown strings return None
        - bool values pass through
        - explicit true/false words map to True/False respectively
    """

    def test_none_returns_none( self ):
        self.assertIsNone( _parse_optional_boolean( None ) )

    def test_bool_passthrough( self ):
        self.assertTrue( _parse_optional_boolean( True ) )
        self.assertFalse( _parse_optional_boolean( False ) )

    def test_semantic_none_returns_none( self ):
        self.assertIsNone( _parse_optional_boolean( "default" ) )
        self.assertIsNone( _parse_optional_boolean( "" ) )

    def test_true_words( self ):
        for w in ( "yes", "true", "1", "enable", "enabled" ):
            self.assertTrue( _parse_optional_boolean( w ), w )

    def test_false_words( self ):
        for w in ( "false", "0", "disable", "disabled", "off" ):
            self.assertFalse( _parse_optional_boolean( w ), w )

    def test_unknown_word_returns_none( self ):
        self.assertIsNone( _parse_optional_boolean( "maybe" ) )


class TestParseOptionalFloat( unittest.TestCase ):
    """
    Exercises `_parse_optional_float`.

    Ensures:
        - valid numeric values parse to float
        - semantic-none / falsy return default
        - unparseable values hit the except arm and return default
    """

    def test_valid_float( self ):
        self.assertEqual( _parse_optional_float( "1.5" ), 1.5 )
        self.assertEqual( _parse_optional_float( 2 ), 2.0 )

    def test_falsy_returns_default( self ):
        self.assertIsNone( _parse_optional_float( "" ) )
        self.assertIsNone( _parse_optional_float( None ) )

    def test_semantic_none_returns_default( self ):
        self.assertIsNone( _parse_optional_float( "none" ) )

    def test_unparseable_hits_except_arm( self ):
        self.assertIsNone( _parse_optional_float( "abc" ) )
        self.assertEqual( _parse_optional_float( "abc", default=3.0 ), 3.0 )


# ---------------------------------------------------------------------------
# create_agentic_job — all ten non-heartbeat command branches
# ---------------------------------------------------------------------------
_JOB_CLASSES = [
    ( "cosa.agents.bug_fix_expediter.job",            "BugFixExpediterJob" ),
    ( "cosa.agents.claude_code.job",                  "ClaudeCodeJob" ),
    ( "cosa.agents.deep_research.job",                "DeepResearchJob" ),
    ( "cosa.agents.deep_research_to_podcast.job",     "DeepResearchToPodcastJob" ),
    ( "cosa.agents.deep_research_to_presentation.job","DeepResearchToPresentationJob" ),
    ( "cosa.agents.podcast_generator.job",            "PodcastGeneratorJob" ),
    ( "cosa.agents.presentation_generator.job",       "PresentationGeneratorJob" ),
    ( "cosa.agents.swe_team.job",                     "SweTeamJob" ),
    ( "cosa.agents.test_fix_expediter.job",           "TestFixExpediterJob" ),
    ( "cosa.agents.test_suite.job",                   "TestSuiteJob" ),
]


class TestCreateAgenticJobBranches( unittest.TestCase ):
    """
    Exercises every non-heartbeat command branch of `create_agentic_job`.

    Requires:
        - each concrete Job class is boundary-mocked at its source module so
          construction is inert (no real agent / LLM / network work)

    Ensures:
        - the correct Job class is constructed for each routing command
        - the per-branch argument parsing produces the expected constructor kwargs
        - `routing_command` + `original_args` are stamped on the returned job
        - an unrecognized command returns None
    """

    def setUp( self ):
        self._patchers = []
        self.mocks     = {}
        for module_path, cls_name in _JOB_CLASSES:
            p = patch( f"{module_path}.{cls_name}", MagicMock( name=cls_name ) )
            self.mocks[ cls_name ] = p.start()
            self._patchers.append( p )

    def tearDown( self ):
        for p in reversed( self._patchers ):
            p.stop()

    def _create( self, command, args ):
        return create_agentic_job(
            command    = command,
            args_dict  = args,
            user_id    = "u1",
            user_email = "u@test.com",
            session_id = "s1",
        )

    # --- deep research --------------------------------------------------
    def test_deep_research_branch( self ):
        job = self._create(
            "agent router go to deep research",
            { "query": "q", "budget": "2.5", "dry_run": "yes", "audience": "a" },
        )
        cls = self.mocks[ "DeepResearchJob" ]
        cls.assert_called_once()
        kw = cls.call_args.kwargs
        self.assertEqual( kw[ "query" ], "q" )
        self.assertEqual( kw[ "budget" ], 2.5 )
        self.assertTrue( kw[ "dry_run" ] )
        self.assertTrue( kw[ "no_confirm" ] )
        self.assertEqual( kw[ "session_id" ], "s1" )
        # stamping
        self.assertEqual( job.routing_command, "agent router go to deep research" )
        self.assertEqual( job.original_args[ "query" ], "q" )

    # --- podcast generator: languages as CSV string ---------------------
    def test_podcast_branch_languages_csv( self ):
        self._create(
            "agent router go to podcast generator",
            { "research": "r.md", "languages": "en, es , fr" },
        )
        kw = self.mocks[ "PodcastGeneratorJob" ].call_args.kwargs
        self.assertEqual( kw[ "research_path" ], "r.md" )
        self.assertEqual( kw[ "target_languages" ], [ "en", "es", "fr" ] )

    # --- podcast generator: languages already a list --------------------
    def test_podcast_branch_languages_list( self ):
        self._create(
            "agent router go to podcast generator",
            { "research": "r.md", "languages": [ "en", "de" ] },
        )
        kw = self.mocks[ "PodcastGeneratorJob" ].call_args.kwargs
        self.assertEqual( kw[ "target_languages" ], [ "en", "de" ] )

    # --- podcast generator: languages omitted (None) --------------------
    def test_podcast_branch_languages_absent( self ):
        self._create( "agent router go to podcast generator", { "research": "r.md" } )
        kw = self.mocks[ "PodcastGeneratorJob" ].call_args.kwargs
        self.assertIsNone( kw[ "target_languages" ] )

    # --- research to podcast: CSV + list both arms ----------------------
    def test_research_to_podcast_branch_csv( self ):
        self._create(
            "agent router go to research to podcast",
            { "query": "q", "languages": "en,es", "budget": "1.0" },
        )
        kw = self.mocks[ "DeepResearchToPodcastJob" ].call_args.kwargs
        self.assertEqual( kw[ "target_languages" ], [ "en", "es" ] )
        self.assertEqual( kw[ "budget" ], 1.0 )

    def test_research_to_podcast_branch_list( self ):
        self._create(
            "agent router go to research to podcast",
            { "query": "q", "languages": [ "ja" ] },
        )
        kw = self.mocks[ "DeepResearchToPodcastJob" ].call_args.kwargs
        self.assertEqual( kw[ "target_languages" ], [ "ja" ] )

    def test_research_to_podcast_branch_languages_absent( self ):
        # languages omitted → the `if args_dict.get("languages")` false arm
        self._create( "agent router go to research to podcast", { "query": "q" } )
        kw = self.mocks[ "DeepResearchToPodcastJob" ].call_args.kwargs
        self.assertIsNone( kw[ "target_languages" ] )

    # --- claude code: _parse_optional_int valid + unparseable -----------
    def test_claude_code_branch( self ):
        self._create(
            "agent router go to claude code",
            { "prompt": "p", "max_turns": "5", "timeout_seconds": "abc", "dry_run": "no" },
        )
        kw = self.mocks[ "ClaudeCodeJob" ].call_args.kwargs
        self.assertEqual( kw[ "prompt" ], "p" )
        self.assertEqual( kw[ "project" ], "lupin" )
        self.assertEqual( kw[ "task_type" ], "BOUNDED" )
        self.assertEqual( kw[ "max_turns" ], 5 )
        self.assertIsNone( kw[ "timeout_seconds" ] )   # "abc" → except arm → None
        self.assertFalse( kw[ "dry_run" ] )

    # --- presentation generator -----------------------------------------
    def test_presentation_branch( self ):
        self._create(
            "agent router go to presentation generator",
            { "source": "s.md", "target_duration_minutes": "10", "render_only": "true" },
        )
        kw = self.mocks[ "PresentationGeneratorJob" ].call_args.kwargs
        self.assertEqual( kw[ "source_path" ], "s.md" )
        self.assertEqual( kw[ "target_duration_minutes" ], 10 )
        self.assertTrue( kw[ "render_only" ] )

    # --- research to presentation ---------------------------------------
    def test_research_to_presentation_branch( self ):
        self._create(
            "agent router go to research to presentation",
            { "query": "q", "budget": "4", "theme": "dark" },
        )
        kw = self.mocks[ "DeepResearchToPresentationJob" ].call_args.kwargs
        self.assertEqual( kw[ "query" ], "q" )
        self.assertEqual( kw[ "budget" ], 4.0 )
        self.assertEqual( kw[ "theme" ], "dark" )

    # --- swe team: `or` defaults on dry_run_phases / dry_run_delay ------
    def test_swe_team_branch_defaults( self ):
        # neither dry_run_phases nor dry_run_delay supplied → `or` defaults fire
        self._create(
            "agent router go to swe team",
            { "task": "do the thing" },
        )
        kw = self.mocks[ "SweTeamJob" ].call_args.kwargs
        self.assertEqual( kw[ "task" ], "do the thing" )
        self.assertEqual( kw[ "dry_run_phases" ], 10 )
        self.assertEqual( kw[ "dry_run_delay" ], 1.5 )

    def test_swe_team_branch_explicit_and_prompt_fallback( self ):
        # task absent → falls back to "prompt"; explicit phases/delay override
        self._create(
            "agent router go to swe team",
            { "prompt": "via-prompt", "dry_run_phases": "3", "dry_run_delay": "0.5" },
        )
        kw = self.mocks[ "SweTeamJob" ].call_args.kwargs
        self.assertEqual( kw[ "task" ], "via-prompt" )
        self.assertEqual( kw[ "dry_run_phases" ], 3 )
        self.assertEqual( kw[ "dry_run_delay" ], 0.5 )

    # --- test suite: csv test_types, csv pytest_args, optional bool -----
    def test_test_suite_branch_csv_args( self ):
        self._create(
            "agent router go to test suite",
            {
                "test_types"          : "unit, integration",
                "pytest_args"         : "-k foo -v",
                "auto_fix_on_failure" : "no",
            },
        )
        kw = self.mocks[ "TestSuiteJob" ].call_args.kwargs
        self.assertEqual( kw[ "test_types" ], [ "unit", "integration" ] )
        self.assertEqual( kw[ "pytest_args" ], [ "-k", "foo", "-v" ] )
        self.assertFalse( kw[ "auto_fix_on_failure" ] )

    def test_test_suite_branch_list_args_and_empty_pytest( self ):
        # test_types already a list; pytest_args is a semantic-none string → []
        self._create(
            "agent router go to test suite",
            {
                "test_types"  : [ "e2e" ],
                "pytest_args" : "none",
            },
        )
        kw = self.mocks[ "TestSuiteJob" ].call_args.kwargs
        self.assertEqual( kw[ "test_types" ], [ "e2e" ] )
        self.assertEqual( kw[ "pytest_args" ], [] )

    def test_test_suite_branch_pytest_args_list_passthrough( self ):
        self._create(
            "agent router go to test suite",
            { "pytest_args": [ "-x" ], "auto_fix_on_failure": "yes" },
        )
        kw = self.mocks[ "TestSuiteJob" ].call_args.kwargs
        self.assertEqual( kw[ "pytest_args" ], [ "-x" ] )
        self.assertTrue( kw[ "auto_fix_on_failure" ] )

    # --- bug fix expediter ----------------------------------------------
    def test_bug_fix_expediter_branch( self ):
        self._create(
            "agent router go to bug fix expediter",
            { "dead_job_id": "dj-1", "lead_model_override": "opus", "thinking_effort": "" },
        )
        kw = self.mocks[ "BugFixExpediterJob" ].call_args.kwargs
        self.assertEqual( kw[ "dead_job_id" ], "dj-1" )
        self.assertEqual( kw[ "lead_model_override" ], "opus" )
        self.assertIsNone( kw[ "thinking_effort" ] )   # "" → `or None`

    # --- test fix expediter: csv-parse original_test_types / pytest_args -
    def test_test_fix_expediter_branch_csv( self ):
        self._create(
            "agent router go to test fix expediter",
            {
                "remediation_snapshot_path" : "snap.json",
                "original_test_types"       : "unit, e2e",
                "original_pytest_args"      : "-k bar",
            },
        )
        kw = self.mocks[ "TestFixExpediterJob" ].call_args.kwargs
        self.assertEqual( kw[ "remediation_snapshot_path" ], "snap.json" )
        self.assertEqual( kw[ "original_test_types" ], [ "unit", "e2e" ] )
        self.assertEqual( kw[ "original_pytest_args" ], [ "-k", "bar" ] )

    def test_test_fix_expediter_branch_list_passthrough( self ):
        # both already lists → no CSV splitting
        self._create(
            "agent router go to test fix expediter",
            {
                "original_test_types"  : [ "integration" ],
                "original_pytest_args" : [ "-v" ],
            },
        )
        kw = self.mocks[ "TestFixExpediterJob" ].call_args.kwargs
        self.assertEqual( kw[ "original_test_types" ], [ "integration" ] )
        self.assertEqual( kw[ "original_pytest_args" ], [ "-v" ] )

    # --- unknown command -------------------------------------------------
    def test_unknown_command_returns_none( self ):
        self.assertIsNone( self._create( "agent router go to nowhere", {} ) )


# ---------------------------------------------------------------------------
# resume_job — full branch matrix
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Queue directives — scheduled_at / monopolize / spawned_by_id_hash
# ---------------------------------------------------------------------------
class _BareJob:
    """A job with its OWN opinions already set, standing in for a real Job class.

    A MagicMock cannot show this defect: every attribute read off a mock answers
    something, so an overwrite and a preserved value look identical.
    """

    def __init__( self, scheduled_at=None, monopolize=False, spawned_by_id_hash=None ):
        self.scheduled_at       = scheduled_at
        self.monopolize         = monopolize
        self.spawned_by_id_hash = spawned_by_id_hash


class TestStampQueueDirectives( unittest.TestCase ):
    """
    Exercises `_stamp_queue_directives`, the seam that carries a caller's queue
    directives onto a built job.

    WHY IT EXISTS. Every endpoint retiring into `/api/v2/submit` set these three on
    the job by hand after this factory returned — `deep_research.py:172`,
    `podcast_generator.py:530`, `swe_team.py:154`, `mock_job.py:185` and the rest —
    and this factory named neither `scheduled_at` nor `monopolize` anywhere. Since
    it reads its arguments key by name, a directive it did not name was dropped in
    silence. As those doors retire there is no handler left to do the stamping, so
    it happens here instead.

    Ensures:
        - a directive the caller SET lands on the job
        - a directive the caller did NOT set leaves the job's own value alone
        - the same job object comes back, not a copy
    """

    def test_a_set_directive_lands_on_the_job( self ):
        job = ajf._stamp_queue_directives( _BareJob(), "2026-08-22T10:30:00-04:00", True, "ts-parent" )
        self.assertEqual( job.scheduled_at, "2026-08-22T10:30:00-04:00" )
        self.assertTrue( job.monopolize )
        self.assertEqual( job.spawned_by_id_hash, "ts-parent" )

    def test_an_unset_directive_does_not_overwrite_the_jobs_own_value( self ):
        """
        RED ON REVERT: drop the `if` guards and write the three unconditionally, and a
        submission that said nothing about scheduling silently disarms a job class that
        had already decided for itself — the monopolize flag being the one that hurts,
        because a job that must run alone would quietly start running beside others.
        """
        job = _BareJob( scheduled_at="2026-08-22T11:00:00-04:00", monopolize=True,
                        spawned_by_id_hash="ts-its-own" )
        ajf._stamp_queue_directives( job, None, False, None )

        self.assertEqual( job.scheduled_at, "2026-08-22T11:00:00-04:00" )
        self.assertTrue( job.monopolize, "an unset monopolize must not disarm a job that set it" )
        self.assertEqual( job.spawned_by_id_hash, "ts-its-own" )

    def test_it_returns_the_same_object( self ):
        """Not a copy: the caller returns what comes back, and a copy would strand the
        constructor's work on an object nobody keeps."""
        job = _BareJob()
        self.assertIs( ajf._stamp_queue_directives( job, None, False, None ), job )


class TestCreateAgenticJobCarriesTheDirectives( unittest.TestCase ):
    """
    The directives reach a job built through the real factory, on BOTH return paths.

    Ensures:
        - the common tail stamps a normally-constructed job
        - the TFE-resume branch, which returns early and skips that tail, stamps too
    """

    def setUp( self ):
        self._patchers = []
        self.mocks     = {}
        for module_path, cls_name in _JOB_CLASSES:
            p = patch( f"{module_path}.{cls_name}", MagicMock( name=cls_name ) )
            self.mocks[ cls_name ] = p.start()
            self._patchers.append( p )

    def tearDown( self ):
        for p in reversed( self._patchers ):
            p.stop()

    def test_the_common_tail_stamps_the_job( self ):
        """RED ON REVERT: return the bare job from the tail and all three asserts fail."""
        self.mocks[ "DeepResearchJob" ].return_value = _BareJob()
        job = create_agentic_job(
            command            = "agent router go to deep research",
            args_dict          = { "query": "q" },
            user_id            = "u1",
            user_email         = "u@test.com",
            session_id         = "s1",
            scheduled_at       = "2026-08-22T10:30:00-04:00",
            monopolize         = True,
            spawned_by_id_hash = "ts-parent",
        )
        self.assertEqual( job.scheduled_at, "2026-08-22T10:30:00-04:00" )
        self.assertTrue( job.monopolize )
        self.assertEqual( job.spawned_by_id_hash, "ts-parent" )

    def test_the_resume_branch_stamps_too( self ):
        """That branch returns before the common tail, so it does its own stamping — a
        caller resuming a stalled job at ten in the morning means it just as much as a
        caller starting fresh work.

        RED ON REVERT: return `resume_job(...)` bare and this fails.
        """
        resumed = _BareJob()
        with patch( "cosa.agents.test_fix_expediter.resume_resolver.resolve_resume_target" ) as resolver, \
             patch.object( ajf, "resume_job", return_value=resumed ) as resume:
            resolver.return_value = MagicMock( job_id="tfe-123" )
            job = create_agentic_job(
                command            = "agent router go to test fix expediter resume",
                args_dict          = { "resume_from": "the stalled one" },
                user_id            = "u1",
                user_email         = "u@test.com",
                session_id         = "s1",
                scheduled_at       = "2026-08-22T10:30:00-04:00",
                monopolize         = True,
            )
        resume.assert_called_once()
        self.assertIs( job, resumed )
        self.assertEqual( job.scheduled_at, "2026-08-22T10:30:00-04:00" )
        self.assertTrue( job.monopolize )

    def test_a_caller_that_names_no_directive_changes_nothing( self ):
        """The default path — every existing caller of this factory, which passes none of
        the three and must keep getting exactly the job it got before."""
        self.mocks[ "DeepResearchJob" ].return_value = _BareJob(
            scheduled_at="2026-08-22T11:00:00-04:00", monopolize=True )
        job = create_agentic_job(
            command    = "agent router go to deep research",
            args_dict  = { "query": "q" },
            user_id    = "u1",
            user_email = "u@test.com",
            session_id = "s1",
        )
        self.assertEqual( job.scheduled_at, "2026-08-22T11:00:00-04:00" )
        self.assertTrue( job.monopolize )
        self.assertIsNone( job.spawned_by_id_hash )


class TestResumeJob( unittest.TestCase ):
    """
    Exercises `resume_job` reconstruction.

    Requires:
        - `job_persistence.get_checkpoint_for_job` / `get_original_args_for_job`
          are patched (no DB)
        - the inner `create_agentic_job` is patched so resume logic is isolated

    Ensures:
        - missing checkpoint / missing job_info / missing routing_command all
          return None
        - the happy path attaches `_resume_checkpoint` and increments
          `resume_count`, merging non-None overrides while skipping None ones
        - a None return from the factory propagates to None
    """

    def _patch_persistence( self, checkpoint, job_info ):
        return (
            patch( "cosa.rest.job_persistence.get_checkpoint_for_job", return_value=checkpoint ),
            patch( "cosa.rest.job_persistence.get_original_args_for_job", return_value=job_info ),
        )

    def test_no_checkpoint_returns_none( self ):
        cp, ji = self._patch_persistence( None, { "routing_command": "x" } )
        with cp, ji:
            self.assertIsNone( resume_job( "h1" ) )

    def test_no_job_info_returns_none( self ):
        cp, ji = self._patch_persistence( { "data": 1 }, None )
        with cp, ji:
            self.assertIsNone( resume_job( "h1" ) )

    def test_no_routing_command_returns_none( self ):
        cp, ji = self._patch_persistence( { "data": 1 }, { "user_id": "u" } )
        with cp, ji:
            self.assertIsNone( resume_job( "h1" ) )

    def test_factory_returns_none_propagates( self ):
        job_info = {
            "routing_command" : "agent router go to deep research",
            "original_args"   : { "query": "q" },
            "user_id"         : "u",
            "user_email"      : "e",
            "session_id"      : "s",
        }
        cp, ji = self._patch_persistence( { "data": 1 }, job_info )
        with cp, ji, patch.object( ajf, "create_agentic_job", return_value=None ):
            self.assertIsNone( resume_job( "h1" ) )

    def test_happy_path_attaches_checkpoint_and_increments( self ):
        checkpoint = { "resume_count": 2, "state": "partial" }
        job_info = {
            "routing_command" : "agent router go to deep research",
            "original_args"   : { "query": "old", "budget": "1.0" },
            "user_id"         : "u",
            "user_email"      : "e",
            "session_id"      : "s",
        }
        fake_job = MagicMock( name="job" )
        cp, ji = self._patch_persistence( checkpoint, job_info )
        with cp, ji, patch.object( ajf, "create_agentic_job", return_value=fake_job ) as mk:
            # overrides: None is skipped, non-None replaces
            result = resume_job( "h1", args_overrides={ "query": "new", "budget": None } )
        self.assertIs( result, fake_job )
        # merged args: query replaced, budget preserved (None override skipped)
        merged = mk.call_args.kwargs[ "args_dict" ]
        self.assertEqual( merged[ "query" ], "new" )
        self.assertEqual( merged[ "budget" ], "1.0" )
        # checkpoint attached + resume_count bumped from 2 → 3
        self.assertIs( fake_job._resume_checkpoint, checkpoint )
        self.assertEqual( fake_job._resume_checkpoint[ "resume_count" ], 3 )

    def test_happy_path_no_overrides_and_default_resume_count( self ):
        checkpoint = { "state": "partial" }   # no resume_count → defaults to 0 → 1
        job_info = {
            "routing_command" : "agent router go to claude code",
            "original_args"   : { "prompt": "p" },
            "user_id"         : "u",
            "user_email"      : "e",
            "session_id"      : "s",
        }
        fake_job = MagicMock( name="job" )
        cp, ji = self._patch_persistence( checkpoint, job_info )
        with cp, ji, patch.object( ajf, "create_agentic_job", return_value=fake_job ) as mk:
            result = resume_job( "h2" )   # args_overrides=None → merge loop skipped
        self.assertIs( result, fake_job )
        self.assertEqual( mk.call_args.kwargs[ "args_dict" ], { "prompt": "p" } )
        self.assertEqual( fake_job._resume_checkpoint[ "resume_count" ], 1 )


def isolated_unit_test():
    """
    Run this module's tests in isolation as a quick smoke check.

    Ensures:
        - returns True when all tests pass, False otherwise
    """
    import sys
    suite  = unittest.TestLoader().loadTestsFromModule( sys.modules[ __name__ ] )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    return result.wasSuccessful()


if __name__ == "__main__":
    isolated_unit_test()
