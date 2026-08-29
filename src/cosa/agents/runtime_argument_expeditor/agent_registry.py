#!/usr/bin/env python3
"""
Agent Registry for Runtime Argument Expeditor.

Maps agentic routing commands to their CLI modules, required arguments,
argument name mappings (LORA -> CLI), fallback questions for missing args,
and fallback default values for pre-populating batch question inputs.

Also provides CLI --help capture with per-process-lifetime caching.
"""

import json
import sys
import subprocess
from typing import Optional


# ============================================================================
# Agent Registry
# ============================================================================

# The two per-user directories every file-typed argument is searched in. They are
# shared because they describe the USER's document library, not any one agent's taste:
# both the podcast and the presentation generator scan both today. An agent that needs
# somewhere else declares its own tuple; this is a default, not a rule.
#
# `{user_email}` is filled in at resolve time. Extensions are per-root because the
# presentations directory holds re-renderable YAML intermediates and nothing else — a
# .md in there would be a rendered output, not a source.
DEFAULT_FILE_SEARCH_ROOTS = (
    { "path": "io/deep-research/{user_email}" },
    { "path": "io/presentations/{user_email}", "extensions": ( ".yaml", ".yml" ) },
)

# What a file-typed argument is searched for when its root does not narrow it.
DEFAULT_FILE_EXTENSIONS = ( ".md", ".yaml", ".yml", ".txt" )


JOB_ARG_CONTRACTS = {
    "agent router go to deep research" : {
        "job_prefix"         : "dr",
        "cli_module"         : "cosa.agents.deep_research.cli",
        "job_class_path"     : "cosa.agents.deep_research.job.DeepResearchJob",
        "display_name"       : "Deep Research",
        "required_user_args" : [ "query" ],
        "system_provided"    : [ "user_email", "session_id", "user_id", "no_confirm" ],
        "arg_mapping"        : {
            "topic"            : "query",
            "query"            : "query",
            "budget"           : "budget",
            "audience"         : "audience",
            "audience_context" : "audience_context",
        },
        "fallback_questions" : {
            "query"            : "What topic would you like me to research?",
            "budget"           : "Would you like to set a budget limit in dollars? Say a dollar amount, or 'no limit'.",
            "audience"         : "Who is the target audience? Options: beginner, intermediate, expert, or academic.",
            "audience_context" : "Any additional context about the audience? Say 'none' to skip.",
        },
        "fallback_defaults" : {
            "budget"           : "no limit",
            "audience"         : "academic",
            "audience_context" : "none",
        },
    },
    "agent router go to podcast generator" : {
        "job_prefix"         : "pg",
        "cli_module"         : "cosa.agents.podcast_generator",
        "job_class_path"     : "cosa.agents.podcast_generator.job.PodcastGeneratorJob",
        "display_name"       : "Podcast Generator",
        "required_user_args" : [ "research" ],
        "system_provided"    : [ "user_id", "user_email", "session_id" ],
        "arg_mapping"        : {
            "research"         : "research",
            "document_path"    : "research",
            # NO `"topic" : "research"` — row 9d89afe2. `research` is a FILE PATH, and all
            # 1200 trained rows for this command emit topic="<subject phrase>", so the alias
            # delivered a spoken subject as a filename (FileNotFoundError on a file nobody
            # named). Unmapped, `topic` keeps its own name, `research` stays MISSING, and the
            # fuzzy_file_match handler below fires and asks which document was meant.
            "audience"         : "audience",
            "audience_context" : "audience_context",
        },
        "fallback_questions" : {
            "research"         : "Which research document should I use for the podcast? Describe it or say the filename.",
            "languages"        : "What languages for the podcast? Use ISO codes like 'en' for English, 'es-MX' for Mexican Spanish, or say the language name.",
            "audience"         : "Who is the target audience? Options: beginner, intermediate, expert, or academic.",
            "audience_context" : "Any additional context about the audience? Say 'none' to skip.",
        },
        "fallback_defaults" : {
            "languages"        : "en,es-MX",
            "audience"         : "academic",
            "audience_context" : "none",
        },
        "special_handlers"   : {
            "research" : "fuzzy_file_match",
        },
        # WHAT KIND OF THING THIS ARGUMENT IS, said once (row a1420538). The expeditor
        # used to learn "research is a file" from the handler tag above and then work
        # out WHERE to look by building a config key from the display name, falling
        # back to the podcast's key when that key was absent — so every other agent's
        # file argument was searched using the podcast's configuration. The roots are
        # declared here instead, beside the argument they belong to.
        "file_args"          : {
            "research" : {
                "kind"             : "file",
                "search_roots"     : DEFAULT_FILE_SEARCH_ROOTS,
                "search_paths_key" : "podcast generator source search paths",
            },
        },
    },
    "agent router go to research to podcast" : {
        "job_prefix"         : "rp",
        "cli_module"         : "cosa.agents.deep_research_to_podcast",
        "job_class_path"     : "cosa.agents.deep_research_to_podcast.job.DeepResearchToPodcastJob",
        "display_name"       : "Research to Podcast",
        "required_user_args" : [ "query" ],
        "system_provided"    : [ "user_email", "session_id", "user_id", "no_confirm" ],
        "arg_mapping"        : {
            "topic"            : "query",
            "query"            : "query",
            "budget"           : "budget",
            "audience"         : "audience",
            "audience_context" : "audience_context",
        },
        "fallback_questions" : {
            "query"            : "What topic would you like me to research and turn into a podcast?",
            "budget"           : "Would you like to set a budget limit for the research phase?",
            "audience"         : "Who is the target audience? Options: beginner, intermediate, expert, or academic.",
            "audience_context" : "Any additional context about the audience? Say 'none' to skip.",
            "languages"        : "What languages for the podcast? Use ISO codes like 'en' for English, 'es-MX' for Mexican Spanish, or say the language name.",
        },
        "fallback_defaults" : {
            "budget"           : "no limit",
            "audience"         : "academic",
            "audience_context" : "none",
            "languages"        : "en,es-MX",
        },
    },
    "agent router go to claude code" : {
        "job_prefix"         : "cc",
        "cli_module"         : "cosa.agents.claude_code",
        "job_class_path"     : "cosa.agents.claude_code.job.ClaudeCodeJob",
        "display_name"       : "Claude Code",
        "required_user_args" : [ "prompt" ],
        "system_provided"    : [ "user_id", "user_email", "session_id" ],
        "arg_mapping"        : {
            "prompt"           : "prompt",
            "task"             : "prompt",
            "project"          : "project",
        },
        "fallback_questions" : {
            "prompt"           : "What coding task would you like Claude Code to work on?",
            "project"          : "Which project should it run against? Options: lupin, cosa, or another project name.",
        },
        "fallback_defaults" : {
            "project"          : "lupin",
            "task_type"        : "BOUNDED",
        },
    },
    "agent router go to presentation generator" : {
        "job_prefix"         : "pr",
        "cli_module"         : "cosa.agents.presentation_generator",
        "job_class_path"     : "cosa.agents.presentation_generator.job.PresentationGeneratorJob",
        "display_name"       : "Presentation Generator",
        "required_user_args" : [ "source" ],
        "system_provided"    : [ "user_id", "user_email", "session_id" ],
        "arg_mapping"        : {
            "source"                  : "source",
            "source_path"             : "source",
            "document"                : "source",
            "file"                    : "source",
            "doc"                     : "source",
            "target_duration_minutes" : "target_duration_minutes",
            "duration"                : "target_duration_minutes",
            "minutes"                 : "target_duration_minutes",
            "target_slide_count"      : "target_slide_count",
            "slide_count"             : "target_slide_count",
            "slides"                  : "target_slide_count",
            "audience"                : "audience",
            "audience_context"        : "audience_context",
            "theme"                   : "theme",
            "render_only"             : "render_only",
            "render"                  : "render_only",
        },
        "fallback_questions" : {
            "source"                  : "Which document should I convert to a presentation, or which YAML to re-render? Describe it or say the filename.",
            "target_duration_minutes" : "How long should the presentation be in minutes? Say a number, or 'default' for 15 minutes.",
            "target_slide_count"      : "How many slides should the presentation have? Say a number, or 'default' to derive it from the duration.",
            "audience"                : "Who is the target audience? Options: beginner, general, expert, or academic.",
            "audience_context"        : "Any additional context about the audience? Say 'none' to skip.",
            "theme"                   : "Which presentation theme? Say 'default' or a theme name.",
        },
        "fallback_defaults" : {
            "target_duration_minutes" : "default",
            "target_slide_count"      : "default",
            "audience"                : "general",
            "audience_context"        : "none",
            "theme"                   : "default",
        },
        "special_handlers" : {
            "source" : "fuzzy_file_match",
        },
        "file_args"        : {
            "source" : {
                "kind"             : "file",
                "search_roots"     : DEFAULT_FILE_SEARCH_ROOTS,
                "search_paths_key" : "presentation generator source search paths",
            },
        },
    },
    "agent router go to research to presentation" : {
        "job_prefix"         : "rx",
        "cli_module"         : "cosa.agents.deep_research_to_presentation",
        "job_class_path"     : "cosa.agents.deep_research_to_presentation.job.DeepResearchToPresentationJob",
        "display_name"       : "Research to Presentation",
        "required_user_args" : [ "query" ],
        "system_provided"    : [ "user_email", "session_id", "user_id" ],
        "arg_mapping"        : {
            "topic"                   : "query",
            "query"                   : "query",
            "question"                : "query",
            "budget"                  : "budget",
            "target_duration_minutes" : "target_duration_minutes",
            "duration"                : "target_duration_minutes",
            "theme"                   : "theme",
            "audience"                : "audience",
            "audience_context"        : "audience_context",
        },
        "fallback_questions" : {
            "query"                   : "What topic should I research and present? Describe the topic or question.",
            "budget"                  : "Research budget in USD? Say a number, or 'default' for unlimited.",
            "target_duration_minutes" : "How long should the presentation be? Say minutes, or 'default' for 15.",
            "theme"                   : "Presentation theme? Say 'default' or a theme name.",
        },
        "fallback_defaults" : {
            "budget"                  : "default",
            "target_duration_minutes" : "default",
            "theme"                   : "default",
            "audience"                : "general",
            "audience_context"        : "none",
        },
    },
    "agent router go to swe team" : {
        "job_prefix"         : "swe",
        "cli_module"         : "cosa.agents.swe_team",
        "job_class_path"     : "cosa.agents.swe_team.job.SweTeamJob",
        "display_name"       : "SWE Team",
        "required_user_args" : [ "task" ],
        "system_provided"    : [ "user_id", "user_email", "session_id" ],
        "arg_mapping"        : {
            "task"             : "task",
            "prompt"           : "task",
            "budget"           : "budget",
            "timeout"          : "timeout",
            "dry_run"          : "dry_run",
        },
        "fallback_questions" : {
            "task"             : "What engineering task should the SWE Team work on?",
            "budget"           : "Would you like to set a budget limit in dollars? Say a dollar amount, or 'no limit'.",
            "timeout"          : "Would you like to set a timeout? Say a number of seconds, or 'default'.",
            "dry_run"          : "Would you like to enable dry run mode? Say 'yes' or 'no'.",
        },
        "fallback_defaults" : {
            "budget"           : "no limit",
            "timeout"          : "default",
            "dry_run"          : "no",
        },
    },

    "agent router go to bug fix expediter" : {
        "job_prefix"         : "bfe",
        "cli_module"         : "cosa.agents.bug_fix_expediter",
        "job_class_path"     : "cosa.agents.bug_fix_expediter.job.BugFixExpediterJob",
        "display_name"       : "Bug Fix Expediter",
        "required_user_args" : [ "dead_job_id" ],
        "system_provided"    : [ "user_id", "user_email", "session_id" ],
        "arg_mapping"        : {
            "dead_job_id"   : "dead_job_id",
            "job_id"        : "dead_job_id",
            "failed_job"    : "dead_job_id",
            "extra_context" : "extra_context",
            "context"       : "extra_context",
            "dry_run"       : "dry_run",
        },
        "fallback_questions" : {
            "dead_job_id"   : "Which failed job would you like me to fix? Provide the job ID.",
            "extra_context" : "Any additional context about the failure? Say 'none' to skip.",
            "dry_run"       : "Would you like to enable dry run mode? Say 'yes' or 'no'.",
        },
        "fallback_defaults" : {
            "extra_context" : "none",
            "dry_run"       : "no",
        },
    },

    "agent router go to test fix expediter" : {
        # START a fresh TFE run — SYSTEM-TRIGGERED, not voice. The test-suite
        # completion watchdog dispatches this command
        # (test_suite_completion_watchdog.py:259) with source_test_suite_job_id =
        # the just-failed job's id_hash. That arg is a job hash no user can speak, so
        # this command is EXEMPT from the router prompt (the drift-guard exemption
        # carries the stated reason + the still-trained residual). It keeps a registry
        # entry so the watchdog's dispatch resolves and the registry OWNS it.
        # cli_module is None (like test_suite): system-dispatched with the arg already
        # supplied, so the voice expeditor never interviews for it — no CLI help, and
        # no shared-module help conflict with the resume entry below.
        "job_prefix"         : "tfe",
        "cli_module"         : None,
        "job_class_path"     : "cosa.agents.test_fix_expediter.job.TestFixExpediterJob",
        "display_name"       : "Test Fix Expediter",
        "required_user_args" : [ "source_test_suite_job_id" ],
        "system_provided"    : [ "user_id", "user_email", "session_id" ],
        "arg_mapping"        : {
            "source_test_suite_job_id" : "source_test_suite_job_id",
            "job_id"                   : "source_test_suite_job_id",
        },
        "fallback_questions" : {
            "source_test_suite_job_id" : "Which test-suite job's failures should I fix? Paste its job ID.",
        },
        "fallback_defaults"  : {},
    },

    "agent router go to test fix expediter resume" : {
        # Voice-driven resume of a stalled Test Fix Expediter job.
        # Session 9056c113 doc 16 Phase 2 — wires into existing REST endpoint
        # POST /api/test-fix-expediter/resume-from via the resume_job() factory.
        # The resume_from arg is resolved via special_handler "tfe_checkpoint_match"
        # which fuzzy-matches user description against stalled/recent TFE jobs.
        "job_prefix"         : "tfe",   # resumed job reuses TFE prefix
        "cli_module"         : "cosa.agents.test_fix_expediter",
        "job_class_path"     : "cosa.agents.test_fix_expediter.job.TestFixExpediterJob",
        "display_name"       : "TFE Resume",
        "required_user_args" : [ "resume_from" ],
        "system_provided"    : [ "user_id", "user_email", "session_id" ],
        "arg_mapping"        : {
            "resume_from"       : "resume_from",
            "job_id"            : "resume_from",
            "plan_path"         : "resume_from",
            "checkpoint"        : "resume_from",
            "description"       : "resume_from",
        },
        "special_handlers"   : {
            "resume_from" : "tfe_checkpoint_match",
        },
        "fallback_questions" : {
            "resume_from" : "Which stalled TFE job would you like to resume? Describe it, paste a job ID (tfe-*), or paste a plan doc path.",
        },
        "fallback_defaults" : {
            # No defaults — resume_from is a required arg with no safe fallback.
        },
    },

    "agent router go to test suite" : {
        "job_prefix"         : "ts",
        "cli_module"         : None,
        "job_class_path"     : "cosa.agents.test_suite.job.TestSuiteJob",
        "display_name"       : "Test Suite",
        "required_user_args" : [],
        "system_provided"    : [ "user_id", "user_email", "session_id" ],
        "arg_mapping"        : {
            "test_types"  : "test_types",
            "suites"      : "test_types",
            "pytest_args" : "pytest_args",
            "dry_run"     : "dry_run",
        },
        "fallback_questions" : {
            "test_types"  : "Which test suites? Options: integration, e2e, or both.",
            "pytest_args" : "Any extra pytest arguments? Say 'none' to skip.",
            "dry_run"     : "Would you like to enable dry run mode? Say 'yes' or 'no'.",
        },
        "fallback_defaults" : {
            "test_types"  : "integration,e2e",
            "pytest_args" : "none",
            "dry_run"     : "no",
        },
    },
}


# ============================================================================
# CLI Help Capture (process-lifetime cache)
# ============================================================================

_help_cache = {}


def get_cli_help( command_key ):
    """
    Capture --help output for an agentic agent's CLI module.

    Requires:
        - command_key is a key in JOB_ARG_CONTRACTS

    Ensures:
        - Returns help text string on success
        - Returns None if command_key not found or subprocess fails
        - Results are cached per-process-lifetime in _help_cache

    Args:
        command_key: Key from JOB_ARG_CONTRACTS (e.g., "agent router go to deep research")

    Returns:
        str or None: CLI help text or None on failure
    """
    if command_key in _help_cache:
        return _help_cache[ command_key ]

    agent_entry = JOB_ARG_CONTRACTS.get( command_key )
    if not agent_entry:
        return None

    cli_module = agent_entry[ "cli_module" ]
    if cli_module is None:
        # Agents without a CLI module (e.g. test_suite, invoked directly via API)
        # have cli_module=None by design. Expeditor's caller handles None help_text.
        _help_cache[ command_key ] = None
        return None

    try:
        result = subprocess.run(
            [ sys.executable, "-m", cli_module, "--help" ],
            capture_output = True,
            text           = True,
            timeout        = 10
        )
        help_text = result.stdout or result.stderr or ""
        _help_cache[ command_key ] = help_text
        return help_text

    except ( subprocess.TimeoutExpired, FileNotFoundError, OSError ) as e:
        print( f"Warning: Failed to capture --help for {cli_module}: {e}" )
        _help_cache[ command_key ] = None
        return None


# ============================================================================
# User-Visible Args Capture (process-lifetime cache)
# ============================================================================

_user_visible_cache = {}


def get_user_visible_args( command_key ):
    """
    Get list of user-visible args for an agent by calling its CLI with --user-visible-args.

    Requires:
        - command_key exists in JOB_ARG_CONTRACTS

    Ensures:
        - Returns list of arg name strings, or None on failure
        - Results are cached for process lifetime

    Args:
        command_key: Key from JOB_ARG_CONTRACTS (e.g., "agent router go to deep research")

    Returns:
        list or None: List of user-visible arg names, or None on failure
    """
    if command_key in _user_visible_cache:
        return _user_visible_cache[ command_key ]

    entry = JOB_ARG_CONTRACTS.get( command_key )
    if not entry:
        return None

    cli_module = entry[ "cli_module" ]
    if cli_module is None:
        # Agents without a CLI module (e.g. test_suite) have cli_module=None by design.
        _user_visible_cache[ command_key ] = None
        return None

    try:
        result = subprocess.run(
            [ sys.executable, "-m", cli_module, "--user-visible-args" ],
            capture_output = True,
            text           = True,
            timeout        = 10
        )
        if result.returncode == 0 and result.stdout.strip():
            args_list = json.loads( result.stdout.strip() )
            _user_visible_cache[ command_key ] = args_list
            return args_list

    except ( subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError ):
        pass

    return None


# ============================================================================
# Smoke Test
# ============================================================================

def quick_smoke_test():
    """
    Quick smoke test for agent_registry module.

    Tests registry structure, key lookups, and help capture.
    """
    import cosa.utils.util as cu
    cu.print_banner( "Agent Registry Smoke Test", prepend_nl=True )

    tests_passed = 0
    tests_failed = 0

    # Test 1: Registry structure
    print( "\n1. Testing registry structure..." )
    try:
        # (count guard deleted 2026-08-15, María: len()==N reads its own source and
        # catches nothing; the drift guard's set-equality is the real content check.)
        for key, entry in JOB_ARG_CONTRACTS.items():
            assert "cli_module" in entry, f"Missing cli_module in {key}"
            assert "required_user_args" in entry, f"Missing required_user_args in {key}"
            assert "system_provided" in entry, f"Missing system_provided in {key}"
            assert "arg_mapping" in entry, f"Missing arg_mapping in {key}"
            assert "fallback_questions" in entry, f"Missing fallback_questions in {key}"
            assert "fallback_defaults" in entry, f"Missing fallback_defaults in {key}"
            assert "display_name" in entry, f"Missing display_name in {key}"
            assert "job_prefix" in entry, f"Missing job_prefix in {key}"
            print( f"   ✓ {key}: structure valid (job_prefix={entry[ 'job_prefix' ]}, display_name={entry[ 'display_name' ]})" )
        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 2: Key lookups
    print( "\n2. Testing key lookups..." )
    try:
        dr = JOB_ARG_CONTRACTS.get( "agent router go to deep research" )
        assert dr is not None
        assert dr[ "required_user_args" ] == [ "query" ]
        print( "   ✓ Deep research lookup works" )

        pg = JOB_ARG_CONTRACTS.get( "agent router go to podcast generator" )
        assert pg is not None
        assert pg[ "required_user_args" ] == [ "research" ]
        assert "special_handlers" in pg
        print( "   ✓ Podcast generator lookup works (has special_handlers)" )

        rp = JOB_ARG_CONTRACTS.get( "agent router go to research to podcast" )
        assert rp is not None
        assert rp[ "required_user_args" ] == [ "query" ]
        print( "   ✓ Research to podcast lookup works" )

        st = JOB_ARG_CONTRACTS.get( "agent router go to swe team" )
        assert st is not None
        assert st[ "required_user_args" ] == [ "task" ]
        assert st[ "display_name" ] == "SWE Team"
        print( "   ✓ SWE Team lookup works" )

        missing = JOB_ARG_CONTRACTS.get( "nonexistent command" )
        assert missing is None
        print( "   ✓ Missing key returns None" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Test 3: Help capture
    print( "\n3. Testing CLI help capture..." )
    try:
        help_text = get_cli_help( "agent router go to deep research" )
        if help_text:
            print( f"   ✓ Help captured ({len( help_text )} chars)" )
        else:
            print( "   ⚠ Help returned None (CLI module may not be available)" )

        # Test cache hit
        help_text_2 = get_cli_help( "agent router go to deep research" )
        assert help_text_2 == help_text, "Cache miss on second call"
        print( "   ✓ Cache hit works" )

        # Test missing key
        help_none = get_cli_help( "nonexistent" )
        assert help_none is None
        print( "   ✓ Missing key returns None" )

        tests_passed += 1
    except Exception as e:
        print( f"   ✗ Failed: {e}" )
        tests_failed += 1

    # Summary
    print( f"\n{'=' * 60}" )
    print( f"Agent Registry Smoke Test: {tests_passed} passed, {tests_failed} failed" )
    print( "=" * 60 )

    return tests_failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
