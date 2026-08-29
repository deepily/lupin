"""
A spoken TOPIC must never fill a FILE-PATH argument — row `9d89afe2`.

╔══════════════════════════════════════════════════════════════════════════════╗
║ RED-FIRST FILE. IF THIS IS FAILING, CHECK YOUR SHA BEFORE REPORTING IT.      ║
║                                                                              ║
║   expected to FAIL  at  78f6683d  — 3 failed, 2 passed                       ║
║   expected to PASS  from 633b9c3c onward — 5 passed                          ║
║                                                                              ║
║ `78f6683d` lands this file while the defect is still live, ON PURPOSE, so    ║
║ the defect is on the record as OBSERVED rather than described. `633b9c3c`    ║
║ is the fix. Both are ancestors of main. A red at `78f6683d` is this file     ║
║ doing its job; a red at or after `633b9c3c` is a real regression — report    ║
║ that one, with your sha.                                                     ║
║                                                                              ║
║ The 2 that pass even at `78f6683d` are the negative controls: the            ║
║ presentation generator's file-shaped aliases stay legal, and the expeditor's ║
║ mapping loop is unchanged.                                                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

THE DEFECT, end to end. Rick says "make me a podcast on KISS". The extractor is
trained as a TOPIC agent: all 1200 `agent router go to podcast generator` rows in
`voice-commands-xml-train.jsonl` emit `topic="<subject phrase>"`, and ZERO emit a
file path or a `research=` value (re-measured 2026-08-24). The registry then
aliases `topic` -> `research` (`agent_registry.py`), and `research` is the
podcast job's SOURCE DOCUMENT PATH. So the subject phrase "KISS" arrives as a
filename, and the job raises FileNotFoundError on a file nobody ever named.

WHY THE ALIAS IS THE FIX AND NOT THE JOB. `research` is declared in `file_args`
with `fuzzy_file_match` as its special handler. When `research` is MISSING, that
fuzzy path fires and the user gets asked which document they meant — the working
behavior. The alias is what prevents `research` from ever being missing: a topic
always fills it, so the fallback that would have saved the interaction never runs.
Removing the alias does not add a code path; it stops suppressing one.

NOT THE SAME AS `research to podcast`. That is a SEPARATE command
(`agent router go to research to podcast`, job class `deep_research_to_podcast`)
with its own 1200 trained rows, which emit `document_path` on 1197 of them and
`topic` on none. A path-emitting podcast route already exists and is trained; this
row is only about the topic-fed one.

⚠️ SCOPE, measured rather than assumed. A survey of all 11 registry entries finds
this alias is UNIQUE to the podcast generator. The presentation generator maps
`source_path` / `document` / `file` / `doc` onto its `source` file arg — every one
of those is a word for a FILE, so they are correct and must stay legal. The bad
shape is specifically a SUBJECT word pointed at a file argument.
"""
import os
import sys

import pytest

sys.path.insert( 0, os.path.join( os.environ[ "LUPIN_ROOT" ], "src" ) )

from cosa.agents.runtime_argument_expeditor.agent_registry import JOB_ARG_CONTRACTS

PODCAST = "agent router go to podcast generator"

# Words that name a SUBJECT the user spoke, never a document on disk. A mapping
# from one of these onto a file-typed argument is the defect this row names.
SUBJECT_ARGS = ( "topic", "subject", "query", "about" )


def _file_args( entry ):
    """The argument names this agent declares as files on disk."""
    return set( entry.get( "file_args", {} ).keys() )


class TestTheSpokenTopicDoesNotBecomeAFilename:

    def test_podcast_generator_does_not_alias_topic_onto_its_file_argument( self ):
        entry   = JOB_ARG_CONTRACTS[ PODCAST ]
        mapping = entry[ "arg_mapping" ]
        files   = _file_args( entry )
        assert "research" in files, (
            "precondition changed: `research` is no longer declared as a file arg, so this "
            "test is asserting about something that no longer exists — re-derive the row."
        )
        assert mapping.get( "topic" ) not in files, (
            "`topic` is aliased onto `%s`, which is a FILE PATH. Every one of the 1200 trained "
            "rows for this command emits topic=<subject phrase>, so a spoken subject arrives as "
            "a filename and the job raises FileNotFoundError. Drop the alias: with `research` "
            "MISSING, its fuzzy_file_match handler fires and asks which document was meant."
            % mapping.get( "topic" )
        )

    def test_no_agent_anywhere_aliases_a_SUBJECT_word_onto_a_file_argument( self ):
        # The class, not the instance. Written as a property over the whole registry
        # so a new agent cannot re-introduce the shape in a place nobody is looking.
        offenders = {}
        for command, entry in JOB_ARG_CONTRACTS.items():
            files = _file_args( entry )
            if not files: continue
            for source, target in entry.get( "arg_mapping", {} ).items():
                if source in SUBJECT_ARGS and target in files:
                    offenders[ command ] = "%s -> %s" % ( source, target )
        assert not offenders, (
            "A word for a SUBJECT is aliased onto a word for a FILE: %s. The user speaks a "
            "topic; the job opens a path. Map subject words to a subject argument, or leave "
            "them unmapped so the file argument stays missing and its fallback fires."
            % offenders
        )

    def test_file_shaped_aliases_stay_LEGAL( self ):
        # The other half of the falsifier. A check that banned every alias onto a file
        # arg would pass the two tests above while breaking the presentation generator,
        # whose source_path/document/file/doc aliases are all correct.
        entry   = JOB_ARG_CONTRACTS[ "agent router go to presentation generator" ]
        mapping = entry[ "arg_mapping" ]
        files   = _file_args( entry )
        legal   = [ s for s, t in mapping.items() if t in files ]
        assert "document" in legal and "file" in legal, (
            "the presentation generator's file-shaped aliases were removed — those are "
            "correct and this row is not about them"
        )


class TestTheMappingLoopStillWorksTheWayThisContractAssumes:
    # The contract tests above are only meaningful while the expeditor still applies
    # arg_mapping as a plain lookup with the LORA name as its own default. If that
    # loop changed, a clean registry would stop implying clean behavior — the
    # assertion would be true and mean nothing.

    def test_an_unmapped_lora_arg_keeps_its_own_name( self ):
        from cosa.agents.runtime_argument_expeditor import expeditor
        import inspect
        source = inspect.getsource( expeditor )
        assert "arg_mapping.get( lora_name, lora_name )" in source, (
            "expeditor.py no longer maps args with `arg_mapping.get( lora_name, lora_name )`. "
            "The registry-contract tests in this file assume that shape: an arg with no alias "
            "keeps its own name and therefore does NOT fill a differently-named required arg. "
            "Re-derive them against the new loop."
        )

    def test_dropping_the_alias_leaves_research_UNFILLED( self ):
        # The behavioral consequence, spelled out against the real registry data:
        # a spoken topic must not end up under the key the job opens as a file.
        entry   = JOB_ARG_CONTRACTS[ PODCAST ]
        mapping = entry[ "arg_mapping" ]
        spoken  = { "topic" : "KISS" }
        mapped  = { mapping.get( k, k ) : v for k, v in spoken.items() }
        assert "research" not in mapped, (
            "a spoken topic still lands in `research`: %s. `research` is opened as a file; "
            "the fuzzy fallback only runs while it is missing." % mapped
        )
        assert mapped == { "topic" : "KISS" }
