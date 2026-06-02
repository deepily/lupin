#!/usr/bin/env python3
"""
Command-Line Interface for COSA Deep Research Agent.

Provides a voice-first CLI for running research queries. Voice I/O is the
PRIMARY interaction mode, with CLI text as automatic fallback.

Usage:
    python -m cosa.agents.deep_research.cli --query "Your research question"
    python -m cosa.agents.deep_research.cli --query "..." --budget 5.00
    python -m cosa.agents.deep_research.cli --query "..." --cli-mode  # Force text mode

Features:
- Voice-first interaction (TTS announcements, voice input)
- Automatic CLI fallback when voice unavailable
- Budget limits for cost control
- Debug output for development
- Cost reporting after completion
"""

import argparse
import asyncio
import logging
import os
import sys
import uuid
from datetime import datetime
from typing import Optional

import yaml

from .config import ResearchConfig
from .cost_tracker import CostTracker, BudgetExceededError
from .api_client import ResearchAPIClient, ANTHROPIC_AVAILABLE, ENV_VAR_NAME, KEY_FILE_NAME
from .orchestrator import ResearchOrchestratorAgent, OrchestratorState  # noqa: F401 — reserved for Phase-3 orchestrator; unused here BY DESIGN (run_research uses a Phase-2 inline flow). Keep, do not strip. Ratified Rick 2026-06-01. See orchestrator.py module docstring.
from . import cosa_interface
from . import voice_io
from . import search_cache

from cosa.config.configuration_manager import ConfigurationManager

logger = logging.getLogger( __name__ )

# Import anthropic for RateLimitError handling
if ANTHROPIC_AVAILABLE:
    import anthropic

# User-visible args: the canonical list of args that end users should see
# and interact with. Engineering params (models, debug, etc.) are excluded.
USER_VISIBLE_ARGS = [ "query", "budget", "audience", "audience_context" ]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="COSA Deep Research Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic research query
  python -m cosa.agents.deep_research.cli --query "Compare React and Vue"

  # With budget limit
  python -m cosa.agents.deep_research.cli --query "..." --budget 5.00

  # Debug mode
  python -m cosa.agents.deep_research.cli --query "..." --debug

  # Non-interactive (skip confirmations)
  python -m cosa.agents.deep_research.cli --query "..." --no-confirm
        """
    )

    parser.add_argument(
        "--query", "-q",
        type=str,
        required=True,
        help="The research query to investigate"
    )

    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Maximum budget in USD (default: unlimited)"
    )

    parser.add_argument(
        "--lead-model",
        type=str,
        default=None,
        help="Model for lead agent (default: claude-opus-4-6)"
    )

    parser.add_argument(
        "--subagent-model",
        type=str,
        default=None,
        help="Model for subagents (default: claude-sonnet-4-6)"
    )

    parser.add_argument(
        "--max-subagents",
        type=int,
        default=10,
        help="Maximum number of parallel subagents (default: 10)"
    )

    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip confirmation prompts (auto-approve)"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output file for the research report"
    )

    parser.add_argument(
        "--no-save",
        action="store_true",
        default=False,
        help="Disable auto-save of report (default: save enabled)"
    )

    parser.add_argument(
        "--save-to-directory",
        type=str,
        default=None,
        help="Override save directory (default: from config manager)"
    )

    parser.add_argument(
        "--user-email",
        type=str,
        default=None,
        help="User email for report folder prefix (multi-tenancy). Required for GCS mode."
    )

    parser.add_argument(
        "--audience",
        type=str,
        choices=[ "beginner", "general", "expert", "academic" ],
        default=None,
        help="Target audience level (default: academic from config). Options: beginner, general, expert, academic"
    )

    parser.add_argument(
        "--audience-context",
        type=str,
        default=None,
        help="Custom audience description (e.g., 'AI architect familiar with distributed systems')"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making API calls"
    )

    parser.add_argument(
        "--cli-mode",
        action="store_true",
        help="Force CLI text mode (disable voice I/O)"
    )

    parser.add_argument(
        "--user-visible-args",
        action  = "store_true",
        default = False,
        help    = "Print user-visible argument names as JSON and exit"
    )

    return parser.parse_args()


def check_prerequisites() -> bool:
    """
    Check that all prerequisites are met.

    Returns:
        bool: True if all prerequisites are met
    """
    # Check anthropic SDK
    if not ANTHROPIC_AVAILABLE:
        print( "ERROR: anthropic SDK not installed" )
        print( "  Install with: pip install anthropic" )
        return False

    # Check API key using firewalled pattern
    # Priority: Environment variable (prod/test) → Local file (dev)
    api_key = os.environ.get( ENV_VAR_NAME )
    key_source = "environment"

    if not api_key:
        # Try local file for development
        try:
            import cosa.utils.util as cu
            api_key = cu.get_api_key( KEY_FILE_NAME )
            key_source = "local file"
        except Exception:
            pass

    if not api_key:
        print( "ERROR: Anthropic API key not found" )
        print( f"  For testing/production: export {ENV_VAR_NAME}=your-key" )
        print( f"  For development: create src/conf/keys/{KEY_FILE_NAME}" )
        print( "" )
        print( "  NOTE: Do NOT use ANTHROPIC_API_KEY (reserved for Claude Code)" )
        return False

    print( f"✓ API key found ({key_source})" )
    return True


def print_header( query: str, config: ResearchConfig, budget: Optional[ float ] ):
    """Print CLI header with configuration."""
    print( "\n" + "=" * 70 )
    print( "  COSA Deep Research Agent" )
    print( "=" * 70 )
    print( f"\nQuery: {query}" )
    print( f"\nConfiguration:" )
    print( f"  Lead Model:     {config.lead_model}" )
    print( f"  Subagent Model: {config.subagent_model}" )
    print( f"  Max Subagents:  {config.max_subagents_complex}" )
    if budget:
        print( f"  Budget Limit:   ${budget:.2f}" )
    else:
        print( f"  Budget Limit:   None (unlimited)" )
    print( "" )


async def run_research(
    query: str,
    config: ResearchConfig,
    cost_tracker: CostTracker,
    user_email: str = "",
    no_confirm: bool = False,
    cancel_check = None,
    debug: bool = False,
    verbose: bool = False
) -> Optional[ str ]:
    """
    Run the research workflow with voice-first interaction.

    Args:
        query: The research query
        config: Research configuration
        cost_tracker: Cost tracker for usage
        user_email: User email for cache directory (multi-tenancy)
        no_confirm: Skip confirmation prompts
        cancel_check: Optional callable returning True if cancellation requested
        debug: Enable debug output
        verbose: Enable verbose output

    Returns:
        str or None: The final research report, or None if cancelled
    """
    # Create API client
    api_client = ResearchAPIClient(
        config       = config,
        cost_tracker = cost_tracker,
        debug        = debug,
        verbose      = verbose,
    )

    # Announce I/O mode
    mode = voice_io.get_mode_description()
    if debug:
        print( f"  [I/O Mode: {mode}]" )

    # For now, we'll use a simplified flow that doesn't use the full orchestrator
    # This is a Phase 2 implementation that demonstrates the API client
    await voice_io.notify( "Step 1 of 4: Analyzing your query", priority="low" )

    # Import prompts
    from .prompts import (
        CLARIFICATION_SYSTEM_PROMPT,
        get_clarification_prompt,
        parse_clarification_response,
        PLANNING_SYSTEM_PROMPT,
        get_planning_prompt,
        parse_planning_response,
    )

    try:
        # Step 1: Clarification
        clarification_response = await api_client.call_with_json_output(
            system_prompt = CLARIFICATION_SYSTEM_PROMPT,
            user_message  = get_clarification_prompt( query ),
            call_type     = "clarification",
        )

        if clarification_response.get( "needs_clarification" ):
            question = clarification_response.get( "question", "Could you clarify?" )
            options = clarification_response.get( "options", [] )

            await voice_io.notify( f"Clarification needed: {question}", priority="medium" )

            if not no_confirm:
                if options and len( options ) >= 2:
                    # Multiple-choice UI when LLM provides structured options
                    clarification = await voice_io.choose(
                        question     = question,
                        options      = options,
                        allow_custom = True  # Still allow "Other" for free-text
                    )
                else:
                    # Fall back to open-ended input for truly open questions
                    clarification = await voice_io.get_input(
                        f"{question} Say your clarification, or say 'skip' to continue without clarifying"
                    )

                if clarification and clarification.lower().strip() not in [ "skip", "none", "no", "" ]:
                    query = f"{query} - Clarification: {clarification}"
                    await voice_io.notify(
                        f"User clarification: {clarification[ :100 ]}",
                        priority="low"
                    )
                else:
                    await voice_io.notify( "User skipped clarification.", priority="low" )

        understood = clarification_response.get( "understood_query", query )
        await voice_io.notify( f"Understood: {understood[:80]}{'...' if len( understood ) > 80 else ''}", priority="low" )

        # Cancel checkpoint: after clarification
        if cancel_check and cancel_check():
            await voice_io.notify( "Research cancelled by user.", priority="medium" )
            return None

        # Step 2: Planning
        await voice_io.notify( "Step 2 of 4: Creating research plan", priority="low" )

        plan_response = await api_client.call_with_json_output(
            system_prompt = PLANNING_SYSTEM_PROMPT,
            user_message  = get_planning_prompt(
                query            = query,
                audience         = config.audience,
                audience_context = config.audience_context
            ),
            call_type     = "planning",
        )

        complexity = plan_response.get( "complexity", "moderate" )
        subqueries = plan_response.get( "subqueries", [] )
        rationale = plan_response.get( "rationale", "" )

        # Announce plan summary
        topics = [ sq.get( "topic", "Unknown" ) for sq in subqueries ]
        plan_summary = f"Found {len( subqueries )} research topics: {', '.join( topics[ :3 ] )}"
        if len( topics ) > 3:
            plan_summary += f" and {len( topics ) - 3} more"
        await voice_io.notify( plan_summary, priority="medium" )

        # ═══════════════════════════════════════════════════════════════════
        # Plan Approval: Progressive Narrowing or Simple Yes/No
        # ═══════════════════════════════════════════════════════════════════

        if not no_confirm and len( subqueries ) > 3:
            # Complex plan (>3 topics) - use progressive narrowing

            # Step A: Cluster into themes
            await voice_io.notify( "Organizing topics into themes for easier selection...", priority="low" )

            from .prompts import THEME_CLUSTERING_PROMPT, get_theme_clustering_prompt

            theme_response = await api_client.call_with_json_output(
                system_prompt = THEME_CLUSTERING_PROMPT,
                user_message  = get_theme_clustering_prompt( subqueries ),
                call_type     = "theme_clustering",
            )
            themes = theme_response.get( "themes", [] )

            # Handle edge cases for theme count (API requires 2-6 options)
            if len( themes ) == 0:
                # Fallback: treat all as single theme
                themes = [ {
                    "name"             : "All Topics",
                    "description"      : f"All {len( subqueries )} research topics",
                    "subquery_indices" : list( range( len( subqueries ) ) )
                } ]

            if len( themes ) == 1:
                # Single theme - skip theme selection, auto-select the only theme
                await voice_io.notify(
                    f"Topics grouped into one theme: {themes[ 0 ][ 'name' ]}. Proceeding to topic selection.",
                    priority="low"
                )
                selected_theme_indices = [ 0 ]

            elif len( themes ) > 6:
                # Too many themes - truncate to first 6 with warning
                await voice_io.notify(
                    f"Found {len( themes )} themes. Showing top 6 for selection.",
                    priority="low"
                )
                themes = themes[ :6 ]
                # Step B: Theme selection (Round 1)
                await voice_io.notify(
                    f"I've organized your research into {len( themes )} themes. "
                    "Sending to your screen for selection.",
                    priority="medium"
                )
                selected_theme_indices = await voice_io.select_themes( themes )

            else:
                # Normal case (2-6 themes) - proceed with selection
                # Step B: Theme selection (Round 1)
                await voice_io.notify(
                    f"I've organized your research into {len( themes )} themes. "
                    "Sending to your screen for selection.",
                    priority="medium"
                )
                try:
                    selected_theme_indices = await voice_io.select_themes( themes )
                except RuntimeError as e:
                    # Technical failure - user already notified by select_themes
                    logger.error( f"Theme selection failed: {e}" )
                    return None

            # Record user's theme selection in job card
            if selected_theme_indices:
                selected_names = [ themes[ i ][ "name" ] for i in selected_theme_indices ]
                await voice_io.notify(
                    f"User selected {len( selected_names )} theme(s): {', '.join( selected_names )}",
                    priority="low"
                )

            if not selected_theme_indices:
                await voice_io.notify( "No themes selected. Research cancelled at your request.", priority="medium" )
                return None

            # Gather topics from selected themes
            selected_subquery_indices = set()
            for ti in selected_theme_indices:
                selected_subquery_indices.update( themes[ ti ].get( "subquery_indices", [] ) )

            candidate_subqueries = [
                ( i, subqueries[ i ] )
                for i in sorted( selected_subquery_indices )
            ]

            # Step C: Topic refinement (Round 2) - only if multiple topics
            if len( candidate_subqueries ) > 2:
                await voice_io.notify(
                    f"You selected {len( candidate_subqueries )} topics. "
                    "Let me show you the details so you can refine further.",
                    priority="low"
                )

                try:
                    selected_indices = await voice_io.select_topics(
                        [ sq for _, sq in candidate_subqueries ]
                    )
                except RuntimeError as e:
                    # Technical failure - user already notified by select_topics
                    logger.error( f"Topic selection failed: {e}" )
                    return None

                # Record user's topic refinement in job card
                if selected_indices:
                    selected_topic_names = [ candidate_subqueries[ i ][ 1 ].get( "topic", "?" ) for i in selected_indices ]
                    await voice_io.notify(
                        f"User refined to {len( selected_indices )} topic(s): {', '.join( selected_topic_names )}",
                        priority="low"
                    )

                if not selected_indices:
                    await voice_io.notify( "No topics selected. Research cancelled at your request.", priority="medium" )
                    return None

                # Map back to original indices
                final_indices = [ candidate_subqueries[ i ][ 0 ] for i in selected_indices ]
            else:
                final_indices = [ i for i, _ in candidate_subqueries ]

            # Filter subqueries to final selection
            subqueries = [ subqueries[ i ] for i in final_indices ]

            await voice_io.notify(
                f"Proceeding with {len( subqueries )} selected topics.",
                priority="medium"
            )

        elif not no_confirm:
            # Simple plan (≤3 topics) - use existing yes/no
            plan_abstract = "Research Plan:\n"
            for i, sq in enumerate( subqueries, 1 ):
                topic = sq.get( 'topic', 'Unknown' )
                objective = sq.get( 'objective', '' )
                plan_abstract += f"  {i}. {topic}"
                if objective:
                    plan_abstract += f"\n     → {objective[:80]}{'...' if len( objective ) > 80 else ''}"
                plan_abstract += "\n"
            plan_abstract += f"\nComplexity: {complexity}\n"
            plan_abstract += f"Estimated searches: {len( subqueries )}"

            proceed = await voice_io.ask_yes_no(
                "Would you like to proceed with this research plan?",
                default="yes",
                abstract=plan_abstract
            )
            await voice_io.notify(
                f"User {'approved' if proceed else 'rejected'} research plan ({len( subqueries )} topics).",
                priority="low"
            )
            if not proceed:
                await voice_io.notify( "Research cancelled.", priority="medium" )
                return None

        # Cancel checkpoint: after planning
        if cancel_check and cancel_check():
            await voice_io.notify( "Research cancelled by user.", priority="medium" )
            return None

        # Step 3: Research (simplified - single call for MVP)
        await voice_io.notify( "Step 3 of 4: Executing research", priority="low" )

        from .prompts import SUBAGENT_SYSTEM_PROMPT, get_subagent_prompt

        # Get rate limiter for progress reporting
        rate_limiter = api_client.get_rate_limiter()

        # Explain rate limiting to user before starting multi-topic research
        if len( subqueries ) > 1:
            await voice_io.notify(
                f"Researching {len( subqueries )} topics. "
                f"Note: Anthropic's web search API is limited to 30,000 tokens per minute, "
                f"but each search typically returns around 80,000 tokens. "
                f"This means we'll need brief pauses between searches to stay within limits.",
                priority="medium"
            )

            # Give time estimate
            estimated_time = rate_limiter.estimate_total_time( len( subqueries ) )
            if estimated_time > 60:
                await voice_io.notify(
                    f"Estimated total research time: {estimated_time / 60:.1f} minutes.",
                    priority="low"
                )

        # Research loop with partial result recovery on rate limit
        findings = []
        rate_limit_hit = False
        cache_hits = 0

        # Progress group ID for in-place DOM updates across all subquery notifications
        research_group_id = f"pg-{uuid.uuid4().hex[ :8 ]}"

        try:
            for i, sq in enumerate( subqueries ):
                # Cancel checkpoint: before each research topic
                if cancel_check and cancel_check():
                    await voice_io.notify( "Research cancelled by user.", priority="medium" )
                    return None

                topic = sq.get( "topic", "Unknown" )
                await voice_io.notify( f"Researching topic {i + 1} of {len( subqueries )}: {topic}", priority="low", progress_group_id=research_group_id )

                # Check cache first
                cached_result = search_cache.load_cached_result( user_email, topic )
                if cached_result:
                    cache_hits += 1
                    if debug: print( f"  [Cache hit] Using cached result for: {topic[:50]}..." )
                    await voice_io.notify( f"Using cached result for topic {i + 1}", priority="low", progress_group_id=research_group_id )

                    # Use cached content directly
                    content = cached_result.get( "results", {} ).get( "content", "" )
                    tokens_used = cached_result.get( "results", {} ).get( "tokens", 0 )

                else:
                    # No cache - make API call
                    subagent_response = await api_client.call_subagent(
                        system_prompt  = SUBAGENT_SYSTEM_PROMPT.format( min_sources=3, max_sources=10 ),
                        user_message   = get_subagent_prompt(
                            topic            = sq.get( "topic", "" ),
                            objective        = sq.get( "objective", "" ),
                            output_format    = sq.get( "output_format", "summary" ),
                            audience         = config.audience,
                            audience_context = config.audience_context,
                        ),
                        subquery_index = i,
                        call_type      = "research",
                    )

                    content = subagent_response.content
                    tokens_used = subagent_response.input_tokens

                    # Save to cache for future use
                    search_cache.save_to_cache(
                        user_email,
                        topic,
                        { "content": content, "tokens": tokens_used }
                    )
                    if debug: print( f"  [Cache saved] Cached result for: {topic[:50]}..." )

                # Parse findings (from cache or API response)
                try:
                    import json
                    # Try to parse as JSON
                    if "```json" in content:
                        json_start = content.index( "```json" ) + 7
                        json_end = content.index( "```", json_start )
                        finding = json.loads( content[ json_start:json_end ].strip() )
                    else:
                        finding = json.loads( content )
                except ( json.JSONDecodeError, ValueError ):
                    # Use raw content if not JSON
                    finding = {
                        "findings"       : content,
                        "subquery_topic" : sq.get( "topic", "" ),
                        "confidence"     : 0.7,
                    }

                finding[ "subquery_topic" ] = sq.get( "topic", "" )
                findings.append( finding )

                # After each call, report progress with token count and next wait estimate
                if i < len( subqueries ) - 1:
                    next_wait = rate_limiter.get_estimated_wait_for_next_call() if not cached_result else 0
                    remaining = len( subqueries ) - i - 1
                    cache_note = " (cached)" if cached_result else ""
                    await voice_io.notify(
                        f"Topic {i + 1}/{len( subqueries )} complete{cache_note} ({tokens_used:,} tokens). "
                        f"{remaining} remaining." + ( f" Next search in ~{next_wait:.0f} seconds." if next_wait > 0 else "" ),
                        priority="low",
                        progress_group_id=research_group_id,
                    )

        except anthropic.RateLimitError:
            # Rate limit hit - offer partial synthesis
            rate_limit_hit = True
            completed = len( findings )
            total = len( subqueries )

            await voice_io.notify(
                f"Rate limit hit after completing {completed} of {total} topics. "
                f"The API limits web searches to 30,000 tokens per minute, but each search returns ~80,000+ tokens.",
                priority="urgent"
            )

            if findings:
                proceed_partial = await voice_io.ask_yes_no(
                    f"Generate partial report from {completed} completed topics?",
                    default="yes"
                )
                await voice_io.notify(
                    f"User {'approved' if proceed_partial else 'declined'} partial report ({completed}/{total} topics).",
                    priority="low"
                )

                if not proceed_partial:
                    await voice_io.notify(
                        "Research paused. You can retry later with fewer topics or wait 1-2 minutes.",
                        priority="medium"
                    )
                    return None
                # If proceed_partial is True, continue to synthesis below
            else:
                await voice_io.notify(
                    "No topics completed before rate limit. Try again in 1-2 minutes.",
                    priority="urgent"
                )
                return None

        if rate_limit_hit:
            await voice_io.notify( f"Proceeding with {len( findings )} partial research findings", priority="medium" )
        else:
            await voice_io.notify( f"Gathered {len( findings )} research findings", priority="low" )

        # Cancel checkpoint: before synthesis
        if cancel_check and cancel_check():
            await voice_io.notify( "Research cancelled by user.", priority="medium" )
            return None

        # Step 4: Synthesis
        await voice_io.notify( "Step 4 of 4: Synthesizing your report", priority="low" )

        from .prompts import SYNTHESIS_SYSTEM_PROMPT, get_synthesis_prompt

        synthesis_response = await api_client.call_lead_agent(
            system_prompt = SYNTHESIS_SYSTEM_PROMPT,
            user_message  = get_synthesis_prompt(
                query            = query,
                findings         = findings,
                plan_summary     = rationale,
                audience         = config.audience,
                audience_context = config.audience_context,
            ),
            call_type     = "synthesis",
            max_tokens    = 8192,
        )

        report = synthesis_response.content
        # Note: Completion notification is sent in main() with enhanced details

        return report

    except BudgetExceededError as e:
        await voice_io.notify( f"Budget exceeded: {e}", priority="urgent" )
        return None

    finally:
        await api_client.close()


async def generate_abstract_for_cli(
    report: str,
    config: ResearchConfig,
    cost_tracker: CostTracker,
    debug: bool = False
) -> str:
    """
    Generate a 2-3 sentence abstract of the research report for CLI use.

    Uses Haiku model for cost efficiency since abstracts are simple
    summarization tasks.

    Requires:
        - report is a non-empty markdown string

    Ensures:
        - Returns concise abstract suitable for YAML frontmatter
        - Captures key findings and conclusions

    Args:
        report: The full research report in markdown format
        config: Research configuration
        cost_tracker: Cost tracker for usage
        debug: Enable debug output

    Returns:
        str: 2-3 sentence abstract summarizing key findings
    """
    api_client = ResearchAPIClient(
        config       = config,
        cost_tracker = cost_tracker,
        debug        = debug,
    )

    try:
        system_prompt = """You are a research summarizer. Generate a concise 2-3 sentence abstract of the research report.
Focus on:
- The main topic/question investigated
- Key findings or conclusions
- One notable insight or recommendation

Keep it factual and direct. No introductory phrases like "This report..." - just state the findings."""

        user_message = f"""Summarize this research report in 2-3 sentences:

{report[:8000]}"""  # Truncate to avoid token limits

        response = await api_client.call_lead_agent(
            system_prompt = system_prompt,
            user_message  = user_message,
            call_type     = "abstract",
            max_tokens    = 256,
        )

        return response.content.strip()

    except Exception as e:
        if debug: print( f"[CLI] Abstract generation error: {e}" )
        # Fallback: extract first meaningful paragraph
        lines = report.split( "\n\n" )
        for line in lines:
            if line.strip() and not line.startswith( "#" ):
                return line.strip()[ :300 ] + "..."
        return "Research report generated."

    finally:
        await api_client.close()


def save_report_with_frontmatter(
    report: str,
    query: str,
    abstract: str,
    semantic_topic: str,
    session_id: str,
    cost_tracker: CostTracker,
    config: ResearchConfig,
    output_dir: str,
    user_email: str,
    storage_backend: str = "local",
    gcs_bucket: Optional[ str ] = None,
    debug: bool = False
) -> str:
    """
    Save research report with YAML frontmatter to local filesystem or GCS.

    Requires:
        - report is a non-empty string
        - user_email is a valid email address for folder prefix
        - For local: output_dir is a valid directory path
        - For GCS: gcs_bucket is a valid GCS bucket URI (gs://...)

    Ensures:
        - Creates output directory/path with user email prefix
        - Writes report with YAML frontmatter including storage metadata
        - Returns the file path (local path or GCS URI)
        - On GCS failure, falls back to local temp file with warning

    Args:
        report: The research report content
        query: Original research query
        abstract: Generated abstract
        semantic_topic: Semantic topic for filename
        session_id: Session identifier
        cost_tracker: Cost tracker with usage data
        config: Research configuration
        output_dir: Local directory to save report to (used for local backend or fallback)
        user_email: User email for folder prefix (multi-tenancy)
        storage_backend: Storage backend - 'local' or 'gcs'
        gcs_bucket: GCS bucket URI when storage_backend='gcs'
        debug: Enable debug output

    Returns:
        str: Path to saved file (local path or GCS URI)
    """
    import cosa.utils.util as cu

    # Generate filename: YYYY.MM.DD-{semantic-topic}.md
    date_str = datetime.now().strftime( "%Y.%m.%d" )
    filename = f"{date_str}-{semantic_topic}.md"

    # Build file path with user email prefix
    if storage_backend == "gcs" and gcs_bucket:
        # GCS path: gs://bucket/{user_email}/{filename}
        # Remove trailing slash from bucket if present
        bucket = gcs_bucket.rstrip( "/" )
        file_path = f"{bucket}/{user_email}/{filename}"
    else:
        # Local path: {output_dir}/{user_email}/{filename}
        user_dir = f"{output_dir}/{user_email}"
        os.makedirs( user_dir, exist_ok=True )
        file_path = f"{user_dir}/{filename}"

    # Get cost summary (SessionSummary is a dataclass, use attribute access)
    summary = cost_tracker.get_summary()
    duration_seconds = summary.duration_seconds
    cost_usd = summary.total_cost_usd
    tokens_used = summary.total_input_tokens + summary.total_output_tokens

    # Build YAML frontmatter with storage metadata
    frontmatter = {
        "query"            : query,
        "abstract"         : abstract,
        "file_path"        : file_path,
        "session_id"       : session_id,
        "user_email"       : user_email,
        "storage backend"  : storage_backend,
        "generated"        : datetime.now().isoformat() + "Z",
        "duration_seconds" : round( duration_seconds, 1 ),
        "cost_usd"         : round( cost_usd, 4 ),
        "tokens_used"      : tokens_used,
        "model"            : config.lead_model,
    }

    # Format YAML with proper string handling
    yaml_content = yaml.dump(
        frontmatter,
        default_flow_style = False,
        allow_unicode      = True,
        sort_keys          = False,
        width              = 120,
    )

    # Combine frontmatter and report
    full_content = f"---\n{yaml_content}---\n\n{report}"

    # Save based on storage backend
    if storage_backend == "gcs" and gcs_bucket:
        try:
            from cosa.utils.util_gcs import write_text_to_gcs
            write_text_to_gcs(
                gcs_uri      = file_path,
                content      = full_content,
                content_type = "text/markdown",
                debug        = debug
            )
            if debug: print( f"[CLI] Report saved to GCS: {file_path}" )
            return file_path

        except Exception as e:
            # GCS write failed - fall back to local temp file
            print( f"\nWARNING: GCS write failed: {e}" )
            print( "  Falling back to local temp file..." )

            # Create temp file in /tmp with similar naming
            import tempfile
            fallback_dir = tempfile.gettempdir()
            fallback_path = f"{fallback_dir}/deep-research-{user_email.replace( '@', '_' )}-{filename}"

            # Update frontmatter to reflect fallback
            frontmatter[ "file_path" ] = fallback_path
            frontmatter[ "storage backend" ] = "local_fallback"
            frontmatter[ "gcs_error" ] = str( e )

            yaml_content = yaml.dump(
                frontmatter,
                default_flow_style = False,
                allow_unicode      = True,
                sort_keys          = False,
                width              = 120,
            )
            full_content = f"---\n{yaml_content}---\n\n{report}"

            with open( fallback_path, "w", encoding="utf-8" ) as f:
                f.write( full_content )

            print( f"  Report saved to fallback location: {fallback_path}" )
            return fallback_path
    else:
        # Local storage
        with open( file_path, "w", encoding="utf-8" ) as f:
            f.write( full_content )

        if debug: print( f"[CLI] Report saved to: {file_path}" )
        return file_path


def main():
    """Main entry point."""
    # Handle --user-visible-args early (before argparse enforces required args)
    if "--user-visible-args" in sys.argv:
        import json
        print( json.dumps( USER_VISIBLE_ARGS ) )
        sys.exit( 0 )

    args = parse_args()

    # Initialize configuration manager
    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    # Get storage configuration
    storage_backend = config_mgr.get( "deep research storage backend", default="local" )
    gcs_bucket      = config_mgr.get( "deep research gcs bucket", default=None )
    gcs_fallback    = False  # Track if we fell back from GCS to local

    # Resolve user_email: CLI arg > config default > error for GCS
    user_email = args.user_email
    if not user_email:
        user_email = config_mgr.get( "deep research default user email", default=None )

    if not user_email:
        # user_email is required for both backends (multi-tenancy)
        print( "ERROR: --user-email is required for multi-tenancy." )
        print( "  Usage: --user-email your@email.com" )
        print( "  Or set 'deep research default user email' in config (Development only)" )
        sys.exit( 1 )

    # Validate user_email format (basic check)
    if "@" not in user_email:
        print( f"ERROR: Invalid email format: {user_email}" )
        print( "  Email must contain '@' character" )
        sys.exit( 1 )

    # Pre-flight GCS check if using GCS backend
    if storage_backend == "gcs":
        if not gcs_bucket:
            print( "ERROR: GCS backend requires 'deep research gcs bucket' config" )
            print( "  Example: deep research gcs bucket = gs://your-bucket/" )
            sys.exit( 1 )

        from cosa.utils.util_gcs import validate_gcs_bucket_access, GCS_AVAILABLE
        if not GCS_AVAILABLE:
            print( "WARNING: GCS SDK not available. Falling back to local storage." )
            storage_backend = "local"
            gcs_fallback = True
        elif not validate_gcs_bucket_access( gcs_bucket, debug=args.debug ):
            print( f"WARNING: GCS bucket not accessible: {gcs_bucket}" )
            print( "  Falling back to local storage." )
            storage_backend = "local"
            gcs_fallback = True

    # Configure voice I/O mode
    if args.cli_mode:
        voice_io.set_cli_mode( True )
        print( "  [CLI mode enabled - voice I/O disabled]" )

    # Generate session_name from query using Gister with custom prompt
    # The prompt generates a human-readable name with spaces (e.g., "cats vs dogs")
    from cosa.memory.gister import Gister
    gister = Gister( debug=args.debug )
    session_name = gister.get_gist( args.query, prompt_key="prompt template for deep research session name" )

    # Post-process session_name: ensure lowercase, preserve spaces for display
    session_name = session_name.lower().strip()
    if not session_name:
        session_name = "general research query"

    # Derive semantic_topic from session_name: convert spaces to hyphens for file naming
    semantic_topic = session_name.replace( " ", "-" )

    if args.debug:
        print( f"  [Session name: {session_name}]" )
        print( f"  [Semantic topic: {semantic_topic}]" )

    # Update cosa_interface sender_id with static #cli suffix (NOT semantic topic)
    cosa_interface.SENDER_ID = cosa_interface._get_sender_id() + "#cli"

    # Set session_name for automatic inclusion in notifications
    cosa_interface.SESSION_NAME = session_name

    # Check prerequisites
    if not args.dry_run and not check_prerequisites():
        sys.exit( 1 )

    # Build configuration from INI (CLI args override)
    config = ResearchConfig.from_config( config_mgr, debug=args.debug )
    if args.lead_model:
        config.lead_model = args.lead_model
    if args.subagent_model:
        config.subagent_model = args.subagent_model
    if args.max_subagents:
        config.max_subagents_complex = args.max_subagents
    if args.audience:
        config.audience = args.audience
    if args.audience_context:
        config.audience_context = args.audience_context

    # Create cost tracker with simplified session_id
    session_id = f"cli-{uuid.uuid4().hex[:8]}"
    cost_tracker = CostTracker(
        session_id       = session_id,
        budget_limit_usd = args.budget,
        debug            = args.debug,
    )

    # Print header
    print_header( args.query, config, args.budget )

    # Dry run mode
    if args.dry_run:
        import cosa.utils.util as cu
        print( "DRY RUN MODE - No API calls will be made" )
        print( f"\nSession name: {session_name}" )
        print( f"Semantic topic (for files): {semantic_topic}" )
        print( f"Session ID: {session_id}" )
        print( f"User email: {user_email}" )
        print( f"Notification sender: {cosa_interface.SENDER_ID}" )
        print( f"\nTarget audience: {config.audience}" )
        if config.audience_context:
            print( f"Audience context: {config.audience_context}" )
        print( f"\nStorage backend: {storage_backend}" )
        if storage_backend == "gcs":
            print( f"GCS bucket: {gcs_bucket}" )
            print( f"Output location: {gcs_bucket.rstrip( '/' )}/{user_email}/" )
        else:
            local_path = cu.get_project_root() + config_mgr.get( "deep research output path" )
            print( f"Output location: {local_path}/{user_email}/" )
        if gcs_fallback:
            print( "  (Fell back from GCS due to access issues)" )
        print( "\nUI will display: lupin#cli {session_name}" )
        print( "\nWould execute:" )
        print( "  1. Query clarification analysis" )
        print( "  2. Research plan generation" )
        print( "  3. Parallel subagent research" )
        print( "  4. Report synthesis" )

        # Send test notification ONLY if voice mode is enabled
        if not args.cli_mode:
            asyncio.run( voice_io.notify(
                f"Dry-run test: session '{session_name}'",
                priority="medium"
            ) )
            print( "\n  ✓ Test notification sent - check UI for sender_id and session_name display" )
        else:
            print( "\n  [Voice mode disabled - skipping test notification]" )

        sys.exit( 0 )

    # Run research
    try:
        report = asyncio.run( run_research(
            query        = args.query,
            config       = config,
            cost_tracker = cost_tracker,
            user_email   = user_email,
            no_confirm   = args.no_confirm,
            debug        = args.debug,
            verbose      = args.verbose,
        ) )

        if report:
            # Print report
            print( "\n" + "=" * 70 )
            print( "  RESEARCH REPORT" )
            print( "=" * 70 )
            print( report )

            # Save to file if requested (raw output without frontmatter)
            if args.output:
                with open( args.output, "w" ) as f:
                    f.write( report )
                print( f"\n  Report saved to: {args.output}" )

            # Auto-save with YAML frontmatter (default: enabled, disable with --no-save)
            save_enabled = not args.no_save
            if save_enabled:
                import cosa.utils.util as cu

                # Determine output directory
                if args.save_to_directory:
                    output_dir = args.save_to_directory
                else:
                    output_dir = cu.get_project_root() + config_mgr.get( "deep research output path" )

                print( "\n  Generating abstract for frontmatter..." )
                abstract = asyncio.run( generate_abstract_for_cli(
                    report       = report,
                    config       = config,
                    cost_tracker = cost_tracker,
                    debug        = args.debug,
                ) )

                file_path = save_report_with_frontmatter(
                    report          = report,
                    query           = args.query,
                    abstract        = abstract,
                    semantic_topic  = semantic_topic,
                    session_id      = session_id,
                    cost_tracker    = cost_tracker,
                    config          = config,
                    output_dir      = output_dir,
                    user_email      = user_email,
                    storage_backend = storage_backend,
                    gcs_bucket      = gcs_bucket,
                    debug           = args.debug,
                )

                # ALWAYS print file path and abstract to stdout
                print( f"\n  Report saved to: {file_path}" )
                print( f"\n  Abstract: {abstract}" )

                # Enhanced notification with frontmatter markdown in abstract field
                summary = cost_tracker.get_summary()
                duration_secs = summary.duration_seconds
                duration_str = f"{int( duration_secs // 60 )}m {int( duration_secs % 60 )}s" if duration_secs >= 60 else f"{duration_secs:.0f}s"
                cost_usd = summary.total_cost_usd
                tokens_used = summary.total_input_tokens + summary.total_output_tokens

                # Determine actual storage backend from file_path (may have changed in fallback)
                actual_backend = "gcs" if file_path.startswith( "gs://" ) else "local"

                # Build links based on storage backend
                import urllib.parse
                if actual_backend == "gcs":
                    from cosa.utils.util_gcs import gcs_uri_to_console_url
                    console_url = gcs_uri_to_console_url( file_path )
                    encoded_path = urllib.parse.quote( file_path, safe="" )
                    view_url = f"http://localhost:7999/api/deep-research/report?path={encoded_path}"
                    links_section = f"""🔗 **View Report**: [Open in Browser]({view_url})
🔗 **Cloud Console**: [View in GCS]({console_url})"""
                else:
                    # Local path - send relative path from io/deep-research base
                    # file_path = /mnt/.../io/deep-research/user@email/file.md
                    # API expects: user@email/file.md
                    deep_research_base = cu.get_project_root() + "/io/deep-research"
                    if file_path.startswith( deep_research_base ):
                        relative_path = file_path[ len( deep_research_base ) + 1: ]  # Skip trailing /
                    else:
                        relative_path = file_path  # Fallback to full path
                    encoded_path = urllib.parse.quote( relative_path, safe="" )
                    view_url = f"/app/docs?path=deep-research/{encoded_path}"
                    links_section = f"""🔗 **View Report**: [Open in Browser]({view_url})"""

                # Build markdown for notification abstract field
                notification_abstract = f"""**Query**: {args.query}

**Abstract**: {abstract}

---

📄 **Report**: `{file_path}`

{links_section}

| Metric | Value |
|--------|-------|
| Duration | {duration_str} |
| Cost | ${cost_usd:.4f} |
| Tokens | {tokens_used:,} |
| Storage | {actual_backend.upper()} |
"""
                asyncio.run( voice_io.notify(
                    "Research complete! Your report is ready.",
                    priority="high",
                    abstract=notification_abstract
                ) )
            else:
                # Basic notification when save is disabled
                asyncio.run( voice_io.notify(
                    "Research complete! Your report is displayed above.",
                    priority="high"
                ) )

        # Print cost summary
        print( "\n" + "=" * 70 )
        print( "  COST SUMMARY" )
        print( "=" * 70 )
        print( cost_tracker.get_cost_report() )

    except KeyboardInterrupt:
        print( "\n\nResearch interrupted by user." )
        print( "\nPartial cost summary:" )
        print( cost_tracker.get_cost_report() )
        sys.exit( 1 )

    except anthropic.RateLimitError:
        # User-friendly rate limit error message
        print( "\n" + "=" * 70 )
        print( "  RATE LIMIT REACHED" )
        print( "=" * 70 )
        print( "\nThe Anthropic API rate limit (30,000 tokens/minute) was exceeded." )
        print( "\nThis can happen when:" )
        print( "  - Web searches return large amounts of content (80,000+ tokens each)" )
        print( "  - Multiple searches run in quick succession" )
        print( "\nSuggested next steps:" )
        print( "  1. Wait 1-2 minutes and try again" )
        print( "  2. Use --max-subagents 2 to limit parallel research" )
        print( "  3. Use a simpler/narrower query" )
        print( "\nPartial cost summary:" )
        print( cost_tracker.get_cost_report() )
        sys.exit( 2 )  # Exit code 2 for rate limit (different from general error)

    except Exception as e:
        print( f"\nError: {e}" )
        if args.debug:
            import traceback
            traceback.print_exc()
        print( "\nPartial cost summary:" )
        print( cost_tracker.get_cost_report() )
        sys.exit( 1 )


if __name__ == "__main__":
    main()
