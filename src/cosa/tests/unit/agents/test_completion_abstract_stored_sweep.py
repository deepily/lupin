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

Scope: the six agents that use the completion_abstract variable pattern —
podcast (real + dry-run), the two deep_research pipelines (dry-run), claude_code
(real + two mock), and the BFE/TFE expediters (real + dry-run). Agents that build
their abstract inline (no completion_abstract variable) are out of this guard's
reach by construction; they are covered by their own suites.
"""

import re

import pytest

import cosa.utils.util as cu

_AGENTS = [
    "podcast_generator",
    "deep_research_to_podcast",
    "deep_research_to_presentation",
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
