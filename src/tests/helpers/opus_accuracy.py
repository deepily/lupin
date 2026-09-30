"""
Pure helpers for the Opus-vs-WAV transcription accuracy check (row 9b1f7701).

Everything here is a FUNCTION OF ITS ARGUMENTS — no subprocess, no network, no
filesystem. That is deliberate: the integration test that uses these needs a live
server and a directory of real phone recordings, so nothing inside it can be
exercised until both exist. The parts that can be wrong on their own — the encode
command ffmpeg is handed, the word error rate arithmetic, the directory
resolution, the libopus probe — live here and are covered by
`src/tests/unit/test_opus_accuracy_helpers.py` at the unit tier, today.

The encode target is ~32 kbps mono Ogg/Opus with libopus's `voip` tuning, which is
what the Android recorder would switch to if the accuracy criterion holds.
"""

import difflib
import os
import re
import unicodedata


# libopus codes these rates natively. Anything else it resamples internally to
# 48 kHz, so asking ffmpeg for the source rate would be a lie about what the
# encoder actually did — target 48000 instead and say so.
OPUS_NATIVE_RATES = ( 8000, 12000, 16000, 24000, 48000 )

# Only wording is compared: case folded, punctuation dropped. Whisper's
# punctuation and capitalisation vary run to run on identical audio, and a
# criterion that counted them would be measuring the transcriber's mood rather
# than the codec.
#
# ⚠️ THIS CLASS IS UNICODE-AWARE ON PURPOSE, and the first cut was not. It read
# [a-z0-9']+, which accepted only the ASCII apostrophe and only ASCII letters —
# and Whisper commonly emits the typographic apostrophe U+2019. Measured: under
# the old class words( "what's" ) was one token but words( "what’s" ) was two,
# so a six-word clip whose two transcripts differed ONLY in quote style scored
# 33% WER — eight times the gate, on punctuation the contract promised to fold
# away. Same class of defect: "café" tokenized as "caf". So: fold the
# apostrophe shapes onto the ASCII one, NFKC-normalize, then match alphanumerics
# in ANY script ([^\W_] is \w minus the underscore) with internal apostrophes kept.
_WORD = re.compile( r"[^\W_]+(?:'[^\W_]+)*" )

# Every apostrophe-shaped character Whisper (or a TTS round trip) can produce,
# mapped to the ASCII one. NFKC does not do this for U+2019 — it is not a
# compatibility equivalent of U+0027 — so it has to be explicit.
#
# ⚠️ THIS MAP IS APPLIED BEFORE NFKC, AND THE ORDER IS LOAD-BEARING. NFKC
# decomposes U+00B4 into a space plus a combining acute accent, so after
# normalizing there is no U+00B4 left for this map to match and the entry is dead
# code: words( "what´s" ) came back as two tokens. Measured on the other five,
# NFKC leaves them alone, so translating first costs nothing and keeps every
# entry live. (The fullwidth apostrophe U+FF07 needs no entry — NFKC folds it to
# U+0027 on its own, and that still happens because normalize runs after.)
_APOSTROPHES = {
    ord( "‘" ) : "'",   # left single quotation mark
    ord( "’" ) : "'",   # right single quotation mark — the common Whisper one
    ord( "‛" ) : "'",   # single high-reversed-9 quotation mark
    ord( "ʼ" ) : "'",   # modifier letter apostrophe
    ord( "´" ) : "'",   # acute accent used as an apostrophe
    ord( "`" ) : "'",   # grave accent used as an apostrophe
}

# A project-relative path in config/tests starts with one of these; anything else
# in LUPIN_TEST_OPUS_ACCURACY_DIR is taken as an absolute host path.
_PROJECT_RELATIVE_PREFIXES = ( "/src/", "/io/" )

# The env var naming the recordings directory. It must start LUPIN_TEST_: a run
# submitted to :8000 passes env_vars through TestSuiteJob's prefix allowlist, which
# silently drops any other name, so the test would skip as "not asked for".
RECORDINGS_ENV = "LUPIN_TEST_OPUS_ACCURACY_DIR"


def opus_target_rate( source_rate ):
    """
    The sample rate to hand libopus for a source recorded at `source_rate`.

    Requires:
        - source_rate is a positive int (Hz)

    Ensures:
        - returns source_rate when libopus codes it natively
        - returns 48000 otherwise, matching what libopus would resample to anyway
    """
    return source_rate if source_rate in OPUS_NATIVE_RATES else 48000


def build_opus_command( src, dst, source_rate, bitrate="32k", application="voip" ):
    """
    The exact ffmpeg argv that encodes one WAV to mono Ogg/Opus.

    Built rather than run so the command is assertable at the unit tier and
    printable in the suite output — a reader of a red run can copy the line.

    Requires:
        - src and dst are paths, source_rate is a positive int (Hz)
        - bitrate is an ffmpeg bitrate string such as "32k"
        - application is one of voip / audio / lowdelay

    Ensures:
        - returns a list of str starting with "ffmpeg" and ending with dst
        - the stream is mono ("-ac", "1") and libopus-coded at `bitrate`, VBR on
        - "-ar" carries opus_target_rate( source_rate ), never an unsupported rate
        - "-y" is present, so a re-run overwrites its own previous output
    """
    return [
        "ffmpeg", "-v", "error", "-y", "-i", str( src ),
        "-c:a", "libopus", "-b:a", bitrate, "-vbr", "on",
        "-application", application, "-ac", "1",
        "-ar", str( opus_target_rate( source_rate ) ),
        str( dst )
    ]


def ffmpeg_has_libopus( encoders_stdout ):
    """
    Whether an `ffmpeg -encoders` listing offers libopus.

    A predicate on the captured text, not on the host, so both answers are
    reachable in a unit test — a skip guard nobody has watched fire is not a guard.

    Requires:
        - encoders_stdout is the stdout of `ffmpeg -hide_banner -encoders`, or ""

    Ensures:
        - returns True iff a listed encoder is named exactly libopus
    """
    for line in ( encoders_stdout or "" ).splitlines():
        fields = line.split()
        # Encoder rows read "<flags> <name> <description>"; the name is field 1.
        if len( fields ) >= 2 and fields[ 1 ] == "libopus": return True
    return False


def resolve_recordings_dir( raw, project_root ):
    """
    Turn the LUPIN_TEST_OPUS_ACCURACY_DIR value into an absolute directory path.

    Requires:
        - raw is the env var's value or None
        - project_root is the absolute project root (cu.get_project_root())

    Ensures:
        - returns None when raw is None, empty, or whitespace only — the caller
          skips on that, it is never silently defaulted to some guessed directory
        - a value starting /src/ or /io/ is joined to project_root, matching how
          the rest of the tree spells a repo-relative path
        - any other value is returned stripped and otherwise untouched
    """
    if raw is None: return None
    value = raw.strip()
    if not value: return None
    if value.startswith( _PROJECT_RELATIVE_PREFIXES ): return project_root + value
    return value


def words( text ):
    """
    Case-folded word tokens of a transcript, with punctuation and quote style folded away.

    Requires:
        - text is a str or None

    Ensures:
        - returns a list of case-folded word tokens, punctuation dropped
        - the typographic apostrophe U+2019 compares equal to the ASCII one, so
          "what's" and "what’s" both tokenize to [ "what's" ]
        - non-ASCII letters survive as letters: "café" is one token, not "caf"
        - compatibility forms are NFKC-folded, so a ligature or a fullwidth digit
          does not read as a different word than its plain spelling
        - returns [] for None or a text with no word characters
    """
    folded     = ( text or "" ).translate( _APOSTROPHES )
    normalized = unicodedata.normalize( "NFKC", folded )
    return _WORD.findall( normalized.casefold() )


def word_error_rate( ref, hyp ):
    """
    Word error rate of `hyp` measured against `ref`.

    ⚠️ THIS IS AN UPPER BOUND, NOT THE MINIMAL EDIT DISTANCE. It is counted off
    difflib's opcodes rather than a Levenshtein table, and difflib looks for long
    matching blocks rather than the cheapest edit script; on a `replace` opcode
    covering unequal spans it then charges max( ref span, hyp span ). A 4000-case
    differential against true Levenshtein found 3.9% of pairs overcounted, worst
    case 1.667 where the true rate was 0.667. The bias is one-directional — the
    number is never BELOW the true rate — which is the safe direction for a gate,
    but it means a SHORT clip can fail the criterion slightly high. Read a
    marginal red with the printed word-level diff in hand before believing it, and
    swap in a real Levenshtein table if the corpus ever lands near the line.

    Requires:
        - ref and hyp are lists of word tokens (see words())

    Ensures:
        - returns ( wer, substitutions, deletions, insertions )
        - wer is ( sub + del + ins ) / len( ref ) when ref is non-empty
        - wer is 0.0 when both are empty, 1.0 when ref is empty and hyp is not
    """
    if not ref:
        return ( 0.0 if not hyp else 1.0 ), 0, 0, len( hyp )

    subs = dels = ins = 0
    matcher = difflib.SequenceMatcher( None, ref, hyp, autojunk=False )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if   tag == "replace": subs += max( i2 - i1, j2 - j1 )
        elif tag == "delete":  dels += i2 - i1
        elif tag == "insert":  ins  += j2 - j1

    return ( subs + dels + ins ) / len( ref ), subs, dels, ins


def word_diff( ref, hyp ):
    """
    Human-readable word-level diff lines between two transcripts.

    Requires:
        - ref and hyp are lists of word tokens

    Ensures:
        - returns [] when the two are identical
        - otherwise returns one line per differing span, naming the opcode and
          quoting the wav-side and opus-side words so a red run is legible
    """
    lines   = []
    matcher = difflib.SequenceMatcher( None, ref, hyp, autojunk=False )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal": continue
        lines.append(
            f"    {tag:<7} wav[{i1}:{i2}]=\"{' '.join( ref[ i1:i2 ] )}\"  "
            f"opus[{j1}:{j2}]=\"{' '.join( hyp[ j1:j2 ] )}\""
        )
    return lines


def corpus_word_error_rate( rows ):
    """
    Pooled word error rate across every compared recording.

    Pooled, NOT the mean of the per-file rates: a ten-word clip and a
    two-hundred-word clip do not deserve equal weight in a corpus criterion.

    Requires:
        - rows is an iterable of dicts carrying int keys
          "wav_words", "subs", "dels", "ins"

    Ensures:
        - returns ( corpus_wer, total_reference_words, total_errors )
        - corpus_wer is 0.0 when the corpus has no reference words at all
    """
    total_ref = sum( r[ "wav_words" ] for r in rows )
    total_err = sum( r[ "subs" ] + r[ "dels" ] + r[ "ins" ] for r in rows )
    return ( total_err / total_ref if total_ref else 0.0 ), total_ref, total_err


def list_wav_files( directory ):
    """
    The .wav basenames in `directory`, sorted, so a run's order is stable.

    Requires:
        - directory is a readable directory path

    Ensures:
        - returns a sorted list of basenames whose extension is .wav, any case

    Raises:
        - FileNotFoundError / NotADirectoryError if directory is not readable
    """
    return sorted( f for f in os.listdir( directory ) if f.lower().endswith( ".wav" ) )
