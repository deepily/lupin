"""
Pins two removals from the legacy page script: a dead playAudioBlob and a fixed email.

The class once defined playAudioBlob twice, so the first, which assigned a Blob to audio.src,
never ran. It also held getCurrentUserEmail, which answered one literal address and had no caller.
"""
import pathlib
import re

STATIC   = pathlib.Path( __file__ ).resolve().parents[ 2 ] / "lupin_app" / "static"
SOURCE   = STATIC / "js" / "notifications.js"
DEF_RX   = re.compile( r"^[ \t]+async playAudioBlob\(", re.M )
FIXED    = "ricardo.felipe.ruiz@gmail.com"


def definitions( text ):
    """Return the offsets of every playAudioBlob definition in a script."""
    return [ m.start() for m in DEF_RX.finditer( text ) ]


def test_the_finder_counts_two_definitions_in_a_script_that_has_two():
    two = "    async playAudioBlob( audioUrl ) {\n    }\n    async playAudioBlob( audioBlob ) {\n    }\n"
    assert len( definitions( two ) ) == 2
    assert len( definitions( "    this.playAudioBlob( x );\n" ) ) == 0


def test_play_audio_blob_is_defined_once():
    assert len( definitions( SOURCE.read_text( encoding="utf-8" ) ) ) == 1


def test_the_surviving_definition_wraps_the_blob_in_an_object_url():
    text  = SOURCE.read_text( encoding="utf-8" )
    start = definitions( text )[ 0 ]
    body  = text[ start:text.index( "\n    }\n", start ) ]
    assert "async playAudioBlob( audioBlob )" in body
    assert "URL.createObjectURL( audioBlob )" in body
    assert "audio.src = audioUrl" not in text


def test_both_callers_pass_a_blob():
    text  = SOURCE.read_text( encoding="utf-8" )
    calls = re.findall( r"this\.playAudioBlob\( ([A-Za-z]+) \)", text )
    assert calls == [ "cachedAudioBlob", "combinedBlob" ]


def test_the_page_script_holds_no_fixed_email_and_no_get_current_user_email():
    text = SOURCE.read_text( encoding="utf-8" )
    assert FIXED not in text
    assert "getCurrentUserEmail" not in text


def test_nothing_else_in_the_static_tree_calls_a_legacy_get_current_user_email():
    # the multiplexer's AuthManager has a method of the same name that reads the token; it is
    # not the legacy page's, so that folder is outside this check
    callers = []
    for path in sorted( STATIC.rglob( "*" ) ):
        if path.suffix not in ( ".js", ".html", ".mjs" ): continue
        if "multiplexer" in path.parts or "dist" in path.parts: continue
        if "getCurrentUserEmail" in path.read_text( encoding="utf-8", errors="replace" ): callers.append( str( path.relative_to( STATIC ) ) )
    assert callers == []
