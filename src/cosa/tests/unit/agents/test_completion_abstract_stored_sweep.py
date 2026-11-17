#!/usr/bin/env python3
"""
Generalized regression guard for bug 9b481811 (done-card abstract) across every
agentic job that builds a completion abstract.

The bug: an agent builds `completion_abstract` and passes it to voice_io.notify
/ cosa_interface.notify_progress, but never stores it in
self.artifacts["abstract"]. running_fifo_queue._transition_to_done builds the
running→done job_state_transition metadata from artifacts.get("abstract"), so an
unstored abstract emits as None and the promoted done card renders blank
("loading…", no Play Here) until a page reload.

INVARIANT (per agent job.py): every `completion_abstract = …` assignment must be
matched by a `self.artifacts["abstract"] = completion_abstract` store. Building an
abstract for the notification but not storing it for the transition is exactly
the bug. This is a static-source guard so a future edit that adds a new
completion path but forgets the store fails here instead of on stage.

Scope: the four agents that use the completion_abstract variable pattern in their own
job.py — podcast (real + dry-run), claude_code (real + two mock), and the BFE/TFE
expediters (real + dry-run). The two deep_research chains build their card in a hook and
store it in the shared frame, `AgenticJobBase._run_chained_pipeline` and
`_run_chained_dry_run`; the frame tests below cover them. Agents that build their
abstract inline (no completion_abstract variable) are out of this guard's reach by
construction; they are covered by their own suites.
"""

import ast
import re

import pytest

import cosa.utils.util as cu

_AGENTS = [
    "podcast_generator",
    "claude_code",
    "bug_fix_expediter",
    "test_fix_expediter",
]

# LHS assignment of the abstract variable: `completion_abstract = …`
_BUILD  = re.compile( r"^\s*completion_abstract\s*=\s*\S", re.MULTILINE )
# The store that carries it onto the transition: `self.artifacts["abstract"] = completion_abstract`
_STORE  = re.compile( r"""artifacts\[\s*["']abstract["']\s*\]\s*=\s*completion_abstract""" )


def _job_src( agent ):
    path = cu.get_project_root() + f"/src/cosa/agents/{agent}/job.py"
    with open( path, encoding="utf-8" ) as fh:
        return fh.read()


@pytest.mark.parametrize( "agent", _AGENTS )
def test_every_completion_abstract_is_stored_for_the_transition( agent ):
    src    = _job_src( agent )
    builds = len( _BUILD.findall( src ) )
    stores = len( _STORE.findall( src ) )
    assert builds > 0, (
        f"{agent}/job.py builds no completion_abstract — either the pattern changed "
        f"or this agent left the scoped set; update _AGENTS deliberately"
    )
    assert stores == builds, (
        f"{agent}/job.py builds {builds} completion_abstract(s) but stores {stores} in "
        f"artifacts['abstract'] — every built abstract must ride the running→done "
        f"transition (bug 9b481811), else its promoted done card renders blank"
    )


def test_control_scanner_actually_matches():
    """A guard whose regexes silently match nothing would pass vacuously."""
    src = _job_src( "podcast_generator" )
    assert _BUILD.findall( src ), "build regex matched nothing — the guard is inert"
    assert _STORE.findall( src ), "store regex matched nothing — the guard is inert"


_CHAIN_JOBS  = [ "deep_research_to_podcast", "deep_research_to_presentation" ]
_FRAME_STORE = re.compile( r"""artifacts\[\s*["']abstract["']\s*\]\s*=\s*completion_abstract""" )


def _function_source( src, name ):
    """Return the source of the method called name in src; fail loudly when there is none."""
    for node in ast.walk( ast.parse( src ) ):
        if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ) and node.name == name:
            return ast.get_source_segment( src, node )
    raise AssertionError( f"no function named {name} in the source" )


@pytest.mark.parametrize( "frame", [ "_run_chained_pipeline", "_run_chained_dry_run" ] )
def test_the_chained_frame_stores_the_abstract_for_the_transition( frame ):
    """Both frame methods store the abstract their hook built; the chain cards ride this store."""
    with open( cu.get_project_root() + "/src/cosa/agents/agentic_job_base.py", encoding="utf-8" ) as fh:
        body = _function_source( fh.read(), frame )
    assert len( _FRAME_STORE.findall( body ) ) == 1, (
        f"{frame} must store completion_abstract in artifacts['abstract'] exactly once "
        f"(bug 9b481811): the chain jobs no longer store it themselves"
    )


@pytest.mark.parametrize( "agent", _CHAIN_JOBS )
def test_each_chain_job_runs_through_the_frame_and_supplies_both_cards( agent ):
    """_execute calls the frame, and the hooks that build the real and dry-run cards exist."""
    src = _job_src( agent )
    assert "self._run_chained_pipeline()" in _function_source( src, "_execute" )
    for hook in ( "_chain_completion", "_store_dry_run_results" ):
        assert _function_source( src, hook ), hook
    assert not _STORE.findall( src ), f"{agent}/job.py stores the abstract itself again; the frame owns the store"
