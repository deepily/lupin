"""Unit tier — the pure parts of the Opus-vs-WAV accuracy check (row 9b1f7701).

The integration test that uses these needs a live :8000 and a directory of real phone
recordings, neither of which exists yet. That would leave the encode command, the word
error arithmetic, the libopus probe and the directory resolution unexercised until the
day they are relied on — so they were factored into `tests.helpers.opus_accuracy` and
are proven here, with no ffmpeg, no server and no audio.

The cases that matter most are the ones a live run could never show you: an ffmpeg
listing WITHOUT libopus (so the skip guard is watched firing), an empty reference
transcript, and a source rate libopus does not code natively.
"""

import pytest

from tests.helpers.opus_accuracy import (
    build_opus_command,
    corpus_word_error_rate,
    ffmpeg_has_libopus,
    opus_target_rate,
    resolve_recordings_dir,
    word_diff,
    word_error_rate,
    words,
)


# ── opus_target_rate ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "source_rate,expected", [
    (  8000,  8000 ),
    ( 12000, 12000 ),
    ( 16000, 16000 ),
    ( 24000, 24000 ),
    ( 48000, 48000 ),
] )
def test_a_natively_coded_rate_is_kept( source_rate, expected ):
    assert opus_target_rate( source_rate ) == expected


@pytest.mark.parametrize( "source_rate", [ 11025, 22050, 32000, 44100, 96000 ] )
def test_a_rate_libopus_cannot_code_becomes_48k( source_rate ):
    # 44100 is the one that matters: it is what the Android recorder writes today, and
    # handing it to -ar would make ffmpeg's command line disagree with what libopus did.
    assert opus_target_rate( source_rate ) == 48000


# ── build_opus_command ───────────────────────────────────────────────────────────────────

def test_the_encode_command_is_mono_32k_libopus_at_the_right_rate():
    command = build_opus_command( "/in/clip.wav", "/out/clip.ogg", 16000 )

    assert command[ 0 ]  == "ffmpeg"
    assert command[ -1 ] == "/out/clip.ogg"
    assert command[ command.index( "-i" ) + 1 ]          == "/in/clip.wav"
    assert command[ command.index( "-c:a" ) + 1 ]        == "libopus"
    assert command[ command.index( "-b:a" ) + 1 ]        == "32k"
    assert command[ command.index( "-ac" ) + 1 ]         == "1"
    assert command[ command.index( "-ar" ) + 1 ]         == "16000"
    assert command[ command.index( "-vbr" ) + 1 ]        == "on"
    assert command[ command.index( "-application" ) + 1 ] == "voip"
    assert "-y" in command


def test_the_encode_command_resamples_a_44k1_source_to_48k():
    command = build_opus_command( "/in/phone.wav", "/out/phone.ogg", 44100 )
    assert command[ command.index( "-ar" ) + 1 ] == "48000"


def test_the_encode_command_honors_an_overridden_bitrate_and_application():
    command = build_opus_command( "/in/a.wav", "/out/a.ogg", 48000, bitrate="24k", application="audio" )
    assert command[ command.index( "-b:a" ) + 1 ]         == "24k"
    assert command[ command.index( "-application" ) + 1 ] == "audio"


def test_the_encode_command_accepts_path_like_arguments_as_strings():
    import pathlib
    command = build_opus_command( pathlib.Path( "/in/a.wav" ), pathlib.Path( "/out/a.ogg" ), 48000 )
    assert all( isinstance( token, str ) for token in command )


# ── ffmpeg_has_libopus ───────────────────────────────────────────────────────────────────

_WITH_LIBOPUS = (
    "Encoders:\n"
    " V..... libx264              libx264 H.264 / AVC\n"
    " A..... libopus              libopus Opus\n"
    " A..... opus                 Opus (native encoder)\n"
)

_WITHOUT_LIBOPUS = (
    "Encoders:\n"
    " V..... libx264              libx264 H.264 / AVC\n"
    " A..... opus                 Opus (native encoder)\n"
)


def test_a_listing_offering_libopus_is_recognised():
    assert ffmpeg_has_libopus( _WITH_LIBOPUS ) is True


def test_a_listing_without_libopus_is_refused():
    # The native "opus" encoder is present here and must NOT count — it is a different,
    # experimental encoder, so a substring check would have said yes and the test would
    # have run against audio nobody asked for.
    assert ffmpeg_has_libopus( _WITHOUT_LIBOPUS ) is False


@pytest.mark.parametrize( "listing", [ "", None, "Encoders:\n" ] )
def test_an_empty_listing_is_refused( listing ):
    assert ffmpeg_has_libopus( listing ) is False


def test_libopus_named_only_in_a_description_does_not_count():
    assert ffmpeg_has_libopus( " A..... opus    Opus (decoder for libopus streams)\n" ) is False


# ── resolve_recordings_dir ───────────────────────────────────────────────────────────────

_ROOT = "/var/lupin"


@pytest.mark.parametrize( "raw", [ None, "", "   ", "\t\n" ] )
def test_an_unset_or_blank_env_var_resolves_to_nothing( raw ):
    # None is the signal the fixture skips on. It must never be a guessed directory.
    assert resolve_recordings_dir( raw, _ROOT ) is None


@pytest.mark.parametrize( "raw,expected", [
    ( "/src/tests/fixtures/audio", "/var/lupin/src/tests/fixtures/audio" ),
    ( "/io/opus-accuracy/recordings", "/var/lupin/io/opus-accuracy/recordings" ),
] )
def test_a_project_relative_path_is_joined_to_the_project_root( raw, expected ):
    assert resolve_recordings_dir( raw, _ROOT ) == expected


@pytest.mark.parametrize( "raw", [ "/home/rruiz/recordings", "/mnt/DATA01/phone/wavs" ] )
def test_an_absolute_host_path_is_left_alone( raw ):
    assert resolve_recordings_dir( raw, _ROOT ) == raw


def test_surrounding_whitespace_is_stripped():
    assert resolve_recordings_dir( "  /io/recordings  ", _ROOT ) == "/var/lupin/io/recordings"


def test_a_lookalike_prefix_is_not_treated_as_project_relative():
    # /source/... starts with "/s" but is not "/src/"; joining it would invent a path.
    assert resolve_recordings_dir( "/source/wavs", _ROOT ) == "/source/wavs"


# ── words ────────────────────────────────────────────────────────────────────────────────

def test_wording_is_compared_case_folded_and_unpunctuated():
    assert words( "What TIME is it?" ) == [ "what", "time", "is", "it" ]


def test_an_apostrophe_stays_inside_a_word():
    assert words( "don't stop" ) == [ "don't", "stop" ]


@pytest.mark.parametrize( "text", [ None, "", "   ", "...  ?!" ] )
def test_a_transcript_with_no_words_tokenizes_to_nothing( text ):
    assert words( text ) == []


def test_digits_are_kept_as_words():
    assert words( "set a timer for 10 minutes" ) == [ "set", "a", "timer", "for", "10", "minutes" ]


# ── words: the quote-style and non-ASCII defect (review fix) ─────────────────────────────
# The first tokenizer read [a-z0-9']+, so it accepted only the ASCII apostrophe and only
# ASCII letters. Whisper commonly emits U+2019, which split a contraction in two, and any
# accented word lost its tail. Both showed up as CODEC error in a check about the codec.

@pytest.mark.parametrize( "apostrophe", [
    "'",   # ASCII apostrophe
    "’",   # right single quotation mark — the common Whisper one
    "‘",   # left single quotation mark
    "ʼ",   # modifier letter apostrophe
] )
def test_every_apostrophe_shape_makes_the_same_token( apostrophe ):
    assert words( f"what{apostrophe}s the weather" ) == [ "what's", "the", "weather" ]


def test_two_transcripts_differing_only_in_quote_style_score_zero():
    # THE REGRESSION, stated as the number it produced: under the old class this pair
    # scored 33% WER on a six-word clip — eight times the 5% gate, on punctuation alone.
    straight = words( "what's the weather like in Madrid" )
    curly    = words( "what’s the weather like in Madrid" )
    assert straight == curly
    assert word_error_rate( straight, curly ) == ( 0.0, 0, 0, 0 )


@pytest.mark.parametrize( "text,expected", [
    ( "café",       [ "café" ] ),
    ( "piñata",     [ "piñata" ] ),
    ( "naïve",      [ "naïve" ] ),
    # casefold(), not lower(): ß folds to "ss", so "Grüße" and "GRÜSSE" compare equal
    # instead of scoring as a substitution.
    ( "Grüße",      [ "grüsse" ] ),
    ( "¿Qué hora?", [ "qué", "hora" ] ),
] )
def test_accented_and_non_ascii_letters_survive_as_letters( text, expected ):
    # "café" tokenized as "caf" under the old class, silently deleting a letter.
    assert words( text ) == expected


def test_a_mixed_clip_that_used_to_blow_the_rate_up_now_scores_zero():
    # One clip, two transcripts, differing ONLY in quote style and punctuation —
    # nothing the codec did. Under the old class this pair did not score zero.
    reference  = words( "we’re meeting at the café, aren’t we" )
    hypothesis = words( "we're meeting at the café aren't we" )
    assert reference == [ "we're", "meeting", "at", "the", "café", "aren't", "we" ]
    assert word_error_rate( reference, hypothesis ) == ( 0.0, 0, 0, 0 )


def test_nfkc_folds_a_compatibility_form_onto_its_plain_spelling():
    # A ligature and a fullwidth digit are the same words as their plain spellings; a
    # criterion that read them as different would be scoring the font, not the codec.
    assert words( "ﬁle" )     == words( "file" )
    assert words( "１０" ) == words( "10" )


def test_case_folding_is_full_not_just_lowercasing():
    assert words( "Grüße" ) == words( "GRÜSSE" )


def test_an_underscore_is_punctuation_here_not_a_word_character():
    # [^\W_] is \w minus the underscore: transcripts are speech, and a stray underscore
    # would otherwise glue two spoken words into one token.
    assert words( "hello_world" ) == [ "hello", "world" ]


# ── word_error_rate ──────────────────────────────────────────────────────────────────────

def test_identical_transcripts_score_zero():
    reference = [ "what", "time", "is", "it" ]
    assert word_error_rate( reference, list( reference ) ) == ( 0.0, 0, 0, 0 )


def test_one_substitution_in_four_words_is_25_percent():
    wer, subs, dels, ins = word_error_rate(
        [ "what", "time", "is", "it" ],
        [ "what", "thyme", "is", "it" ]
    )
    assert ( subs, dels, ins ) == ( 1, 0, 0 )
    assert wer == pytest.approx( 0.25 )


def test_a_dropped_word_counts_as_a_deletion():
    wer, subs, dels, ins = word_error_rate(
        [ "what", "time", "is", "it" ],
        [ "what", "time", "it" ]
    )
    assert ( subs, dels, ins ) == ( 0, 1, 0 )
    assert wer == pytest.approx( 0.25 )


def test_an_extra_word_counts_as_an_insertion():
    wer, subs, dels, ins = word_error_rate(
        [ "what", "time", "is", "it" ],
        [ "so", "what", "time", "is", "it" ]
    )
    assert ( subs, dels, ins ) == ( 0, 0, 1 )
    assert wer == pytest.approx( 0.25 )


def test_a_replace_over_unequal_spans_charges_the_longer_side():
    # Two reference words become three. Charging min() would report 2 errors and
    # undercount; the criterion must err toward reporting MORE error, not less.
    wer, subs, dels, ins = word_error_rate(
        [ "alpha", "beta", "gamma", "delta" ],
        [ "alpha", "bee", "tah", "gah", "delta" ]
    )
    assert subs == 3
    assert wer == pytest.approx( 0.75 )


def test_two_empty_transcripts_score_zero_not_one():
    assert word_error_rate( [], [] ) == ( 0.0, 0, 0, 0 )


def test_an_empty_reference_with_words_against_it_scores_one():
    wer, subs, dels, ins = word_error_rate( [], [ "hello", "there" ] )
    assert wer == 1.0
    assert ins == 2


def test_an_empty_hypothesis_against_a_full_reference_scores_one():
    wer, subs, dels, ins = word_error_rate( [ "what", "time", "is", "it" ], [] )
    assert wer == pytest.approx( 1.0 )
    assert dels == 4


# ── word_diff ────────────────────────────────────────────────────────────────────────────

def test_identical_transcripts_produce_no_diff_lines():
    assert word_diff( [ "a", "b" ], [ "a", "b" ] ) == []


def test_a_diff_line_quotes_both_sides_and_names_the_opcode():
    lines = word_diff( [ "what", "time", "is", "it" ], [ "what", "thyme", "is", "it" ] )
    assert len( lines ) == 1
    assert "replace" in lines[ 0 ]
    assert "time"  in lines[ 0 ]
    assert "thyme" in lines[ 0 ]


def test_every_differing_span_gets_its_own_line():
    lines = word_diff( [ "a", "b", "c", "d", "e" ], [ "x", "b", "c", "d", "y", "e" ] )
    assert len( lines ) == 2


# ── corpus_word_error_rate ───────────────────────────────────────────────────────────────

def _row( wav_words, subs=0, dels=0, ins=0 ):
    return { "wav_words": wav_words, "subs": subs, "dels": dels, "ins": ins }


def test_the_corpus_rate_pools_errors_rather_than_averaging_per_file_rates():
    # A 10-word clip with 5 errors (50%) and a 190-word clip with 0. The mean of the
    # per-file rates is 25%; the pooled rate is 2.5%. Pooled is the honest number and
    # is what the criterion is stated against.
    corpus, total_ref, total_err = corpus_word_error_rate( [ _row( 10, subs=5 ), _row( 190 ) ] )
    assert ( total_ref, total_err ) == ( 200, 5 )
    assert corpus == pytest.approx( 0.025 )


def test_the_corpus_rate_sums_all_three_error_kinds():
    corpus, total_ref, total_err = corpus_word_error_rate( [ _row( 100, subs=2, dels=3, ins=5 ) ] )
    assert total_err == 10
    assert corpus == pytest.approx( 0.10 )


def test_a_corpus_with_no_reference_words_is_zero_not_a_zero_division():
    assert corpus_word_error_rate( [] ) == ( 0.0, 0, 0 )
    assert corpus_word_error_rate( [ _row( 0, ins=3 ) ] ) == ( 0.0, 0, 3 )
