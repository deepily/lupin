"""
Gated unit tests for prosody marker counting (row 52912c4f).

The measurement defect: validate_prosody_preservation counted seg.prosody (the
LIST field), which the translation path never populates, so it reported total
prosody loss ("es-MX=0") for scripts whose TEXT carried the markers inline. The
fix counts from the segment text via the shared extract_prosody_markers helper.

These tests are the gate: they assert the count follows the TEXT even when the
prosody list is empty or wrong, and that a genuine marker loss is still caught.

Venue: :7999 (pure, in-memory model objects, no server) — meets all three
§TESTING VENUES criteria.

NOTE ON WORTH: a correct count is cosmetic until the TTS honors the markers.
Today the audio path strips every *[marker]* before synthesis (row 03d41dd8),
so this fix makes the measurement honest, not the audio expressive.
"""

import pytest

from cosa.agents.podcast_generator.state import (
    ScriptSegment,
    PodcastScript,
    extract_prosody_markers,
    strip_prosody_markers,
    validate_prosody_preservation,
)


def _seg( text, prosody=None ):
    # prosody defaults to [] — as it arrives on the translation path — so the
    # tests prove the count comes from `text`, not from this list.
    return ScriptSegment( speaker="Nora", role="curious", text=text, prosody=prosody or [] )


def _script( segments ):
    return PodcastScript(
        title="T", research_source="r.md", host_a_name="Nora", host_b_name="Ivo",
        segments=segments,
    )


# ---- the helper -----------------------------------------------------------

@pytest.mark.parametrize( "text,expected", [
    ( None,                              [] ),
    ( "",                               [] ),
    ( "plain text, no markers",         [] ),
    ( "*[pause]* hi",                   [ "pause" ] ),
    ( "*[Excited]* hi *[PAUSE]* there", [ "excited", "pause" ] ),   # lowercased
    ( "*[  chuckles  ]* hey",           [ "chuckles" ] ),           # stripped
] )
def test_extract_prosody_markers( text, expected ):
    assert extract_prosody_markers( text ) == expected


# ---- the strip helper, and the one place the pattern lives ----------------

@pytest.mark.parametrize( "text,expected", [
    ( "",                                    "" ),
    ( "plain  text",                         "plain text" ),
    ( "*[pause]* hi",                        "hi" ),
    ( "So *[pause]* what *[excited]* now",   "So what now" ),
    ( "tail *[laughs]*",                     "tail" ),
    ( "  *[x]*  ",                           "" ),
    ( "a\n*[x]*\tb",                        "a b" ),                  # a tab or newline is whitespace too
    ( 'keep <break time="1.0s"/> and WOW...', 'keep <break time="1.0s"/> and WOW...' ),
    ( "*[]* stays, *[a]b* stays",            "*[]* stays, *[a]b* stays" ),   # not a marker: empty or unclosed
] )
def test_strip_prosody_markers( text, expected ):
    assert strip_prosody_markers( text ) == expected


@pytest.mark.parametrize( "text", [ "a *[pause]* b *[Excited]* c", "*[x]* y", "no markers here" ] )
def test_strip_removes_exactly_what_extract_counts( text ):
    # The two helpers share one pattern: whatever extract counts, strip removes, and nothing else goes.
    assert ( "*[" in strip_prosody_markers( text ) ) is False
    assert len( extract_prosody_markers( text ) ) == text.count( "*[" )


def test_strip_prosody_markers_refuses_none():
    with pytest.raises( TypeError ):
        strip_prosody_markers( None )


def test_both_callers_go_through_the_shared_helpers():
    from cosa.agents.podcast_generator.prompts.script_generation import extract_prosody_from_text
    from cosa.agents.podcast_generator.tts_client import PodcastTTSClient
    text = "So *[pause]* what *[Excited]* now"
    assert extract_prosody_from_text( text ) == ( "So what now", [ "pause", "excited" ] )
    assert PodcastTTSClient._clean_text_for_tts( None, text ) == "So what now"


def test_every_prosody_marker_pattern_lives_in_state():
    # Census: one copy of the marker regex under podcast_generator. A second copy is how the three drifted apart.
    import subprocess, os
    root  = os.environ[ "LUPIN_ROOT" ]
    files = subprocess.run( [ "git", "ls-files", "src/cosa/agents/podcast_generator/*.py" ],
                            cwd=root, capture_output=True, text=True, check=True ).stdout.split()
    assert len( files ) > 5, "the census walked the wrong population"
    holders = []
    for rel in files:
        if "/tests/" in rel: continue
        with open( os.path.join( root, rel ), encoding="utf-8" ) as fh:
            if r"\*\[" in fh.read(): holders.append( rel )
    # state.py also holds the segment-header pattern, which has the same opening; it is the only holder.
    assert holders == [ "src/cosa/agents/podcast_generator/state.py" ]


# ---- the validator counts TEXT, not the list ------------------------------

def test_count_comes_from_text_when_prosody_list_empty():
    # Both sides carry the markers inline but the prosody LISTS are empty —
    # exactly the translation-path shape that produced the false "es-MX=0".
    english    = _script( [ _seg( "*[excited]* Welcome *[pause]* back" ) ] )
    translated = _script( [ _seg( "*[excited]* Bienvenidos *[pause]* de nuevo" ) ] )
    ok, details = validate_prosody_preservation( english, translated )
    assert details[ "english_count" ]    == 2
    assert details[ "translated_count" ] == 2      # would be 0 counting seg.prosody
    assert ok is True
    assert details[ "missing" ] == [] and details[ "extra" ] == []


def test_prosody_list_is_ignored_when_it_disagrees_with_text():
    # A wrong/ghost prosody list must not sway the count — only the text does.
    english    = _script( [ _seg( "*[pause]* hi",  prosody=[ "ghost", "phantom" ] ) ] )
    translated = _script( [ _seg( "*[pause]* hola", prosody=[] ) ] )
    ok, details = validate_prosody_preservation( english, translated )
    assert details[ "english_count" ]    == 1      # 'pause' from text, not 2 ghosts
    assert details[ "translated_count" ] == 1
    assert ok is True


def test_genuine_marker_loss_is_still_caught():
    # The translation dropped the *[pause]* — the validator must report it lost.
    english    = _script( [ _seg( "*[excited]* Welcome *[pause]* back" ) ] )
    translated = _script( [ _seg( "*[excited]* Bienvenidos" ) ] )      # no pause
    ok, details = validate_prosody_preservation( english, translated )
    assert ok is False
    assert "pause" in details[ "missing" ]
    assert details[ "extra" ] == []


def test_extra_marker_in_translation_is_caught():
    english    = _script( [ _seg( "*[excited]* Welcome" ) ] )
    translated = _script( [ _seg( "*[excited]* Bienvenidos *[laughs]*" ) ] )
    ok, details = validate_prosody_preservation( english, translated )
    assert ok is False
    assert "laughs" in details[ "extra" ]


# ---- the parser fills seg.prosody via the SAME helper (no drift) -----------

def test_from_markdown_populates_prosody_via_shared_helper():
    md = "# Podcast: Test\n**[Nora - Curious]**: *[excited]* Hello *[pause]* world"
    script = PodcastScript.from_markdown( md )
    seg = script.segments[ 0 ]
    assert seg.prosody == [ "excited", "pause" ]                  # extracted from text
    assert extract_prosody_markers( seg.text ) == seg.prosody     # parser == validator source
