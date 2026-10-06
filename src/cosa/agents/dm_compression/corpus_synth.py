"""
A synthetic DM corpus for the freeze property tests: deterministic, in-repo, no artifact.

Why it exists: the corpus tests in `test_freeze.py` once read a 4 MB snapshot of real fleet
DM traffic from the gitignored `src/tmp/`. With the file present the module reported 494
passed. With it absent, 488 passed and 6 skipped, and `git status` could not say which run you got.
The real snapshot never goes in the repo. It holds real message bodies and personal email
addresses, and the repo's secret scanner cannot read `.jsonl` files.

A corpus in code cannot go missing. Generating the bodies in a committed module leaves no
path to check and no artifact to forget. The suite has no second mode in which it measures
less and still says "passed".

What the tests discriminate on: all six are property tests. They cover freeze and restore
round-trips, and placeholder tokens never colliding with source text. They also cover the
validator's verdict not depending on a span's label, and resolved spans never overlapping.
The last two are no unrestored placeholder reaching delivery and `compress_or_original`
never raising. None cares whether the text reads like a conversation. They need text that
strains the span extractor: every pattern kind, plus nesting, adjacency, and literals on
each other's boundaries.

What it does not cover, so read a green with care:
 - It exercises only the kinds this file builds. The coverage test derives the kind list from
   `freeze._PATTERNS` at runtime, so a new pattern reddens it. That does not make the
   arrangements exhaustive, and they cannot be.
 - It cannot produce combinations nobody designed, which is what real traffic supplied.
 - It is not a statistical model of fleet traffic. Lengths and shapes stress the extractor.

A green means the invariants hold on adversarial text we thought of, never on real traffic.

Determinism: `synth_corpus()` takes an explicit seed and returns the same bodies every call.
A failure is reproducible from the seed alone.
"""

import random


# One representative literal per pattern kind, keyed by the kind name in `freeze._PATTERNS`
# so the coverage test can diff this against the live pattern list — a kind added there and
# forgotten here is a RED, not a silent gap.
#
# Every value is invented. No credential, host, address or path here refers to anything
# real, and nothing was copied out of the traffic snapshot.
_LITERALS = {
    "FENCE"    : "```def handler(): return 42```",
    "CODE"     : "`queue_list`",
    "URL"      : "https://example.invalid/docs/page?q=1",
    "EMAIL"    : "nobody@example.invalid",
    "ROUTE"    : "POST /api/v2/submit",
    "MOUNT"    : "./src/conf:/app/conf",
    "WINPATH"  : "C:\\Users\\nobody\\notes.txt",
    "FILELINE" : "queue_consumer.py:214",
    "PATH"     : "src/cosa/rest/queue_protocol.py",
    "FILENAME" : "lupin-app.ini",
    "UUID"     : "3f2b91ce-0a4d-4c7e-9b11-77de0a5c6e42",
    "SHA"      : "d256e25a",
    "IP"       : "203.0.113.7",
    "ISOTS"    : "2026-08-30T11:04:22-04:00",
    "ISODATE"  : "2026-08-30",
    "SEMVER"   : "v0.2.1",
    "PORT"     : ":7999",
    "ISSUE"    : "#4127",
    "SECTION"  : "\u00a73a",
    "FLAG"     : "--force-recreate",
    "KEYVAL"   : "timeout=30",
    "CONST"    : "MAX_RETRY_COUNT",
    "IDENT"    : "RunningFifoQueue",
    "DELTA"    : "+12/-4",
    "SECRET"   : "NOT_A_REAL_SECRET_ONLY_A_PATTERN_FIXTURE",  # 40 chars of [A-Za-z0-9_], which is
                # all the SECRET pattern asks for. The first draft used a random-looking string and
                # the pre-commit scanner blocked it — correctly, since it cannot tell invented from
                # real. A fixture that has to be waved past a secret gate is the wrong fixture.
    "GLYPH"    : "\U0001F33B",
    "QUOTE"    : '"the consumer thread returns early"',
    "MONEY"    : "$2.05",
    "NUMUNIT"  : "648s",
    "NUMWORD"  : "three hundred",   # SPELLED OUT, and TWO+ words chained — the pattern needs both
}

# Sentence frames the literals drop into. Deliberately mundane — prose is packaging, the
# literals are the payload.
_FRAMES = [
    "I traced it to {a} this morning and {b} looks wrong.",
    "Check {a} before you touch {b}, the two disagree.",
    "{a} landed clean but {b} is still red on my box.",
    "Nothing in {a} explains {b}; I read both twice.",
    "Ran it again: {a}, then {b}, same result.",
    "The report says {a} while the log says {b}.",
]

# The awkward arrangements — the half a frame-filler cannot reach. Each puts a literal on
# another literal's boundary, which is where span resolution actually breaks.
_ADVERSARIAL = [
    'he said "the fix is `d256e25a` exactly" yesterday',
    "see src/cosa/rest/queue.py:214 and queue.py:215 too",
    "```\nGET /api/busy\nhost: 203.0.113.7\n```",
    "`--flag=value` and --flag=value differ",
    "v0.2.1-rc1+build.7 is not v0.2.1",
    "2026-08-30T11:04:22Z, 2026-08-30, and 2026.08.30",
    "MAX_RETRY_COUNT=3 in lupin-app.ini \u00a73a",
    "nobody@example.invalid/not-a-path",
    "port :7999 and ratio 7999:1 are different",
    "\u00ab\U0001F33B\U0001F989\U0001F451\u00bb run of glyphs mid-sentence",
    "```nested ``` fence``` edge",
    'unterminated "quote and `code without a close',
    "\u27e6NOT_A_REAL_PLACEHOLDER\u27e7 typed by a human",
    "",
    "   ",
    "a",
]


def synth_corpus( count=600, seed=20260830 ):
    """
    Build a deterministic list of synthetic DM bodies.

    Requires:
        - count is a non-negative int
        - seed is an int

    Ensures:
        - returns a list of str bodies, never shorter than the adversarial set plus one
          body per literal kind
        - the same seed always yields the same bodies, so a failure is reproducible from
          the seed alone
        - every kind in `_LITERALS` appears somewhere in the result
        - the adversarial cases come first, so a truncated slice (`corpus[ :300 ]`, which
          four of the six tests take) still contains them — a generator whose hard cases
          sort to the end is tested by nobody
    """
    rng    = random.Random( seed )
    bodies = list( _ADVERSARIAL )
    kinds  = sorted( _LITERALS )

    # One body per kind, so coverage never depends on the random draw.
    for kind in kinds:
        bodies.append( f"Checking {_LITERALS[ kind ]} in isolation, nothing else here." )

    floor = len( _ADVERSARIAL ) + len( kinds )

    while len( bodies ) < count:
        frame = rng.choice( _FRAMES )
        a, b  = rng.sample( kinds, 2 )
        body  = frame.format( a=_LITERALS[ a ], b=_LITERALS[ b ] )

        # Some bodies get a second sentence, so the corpus is not uniformly one-line.
        if rng.random() < 0.4:
            c, d  = rng.sample( kinds, 2 )
            body += " " + rng.choice( _FRAMES ).format( a=_LITERALS[ c ], b=_LITERALS[ d ] )

        bodies.append( body )

    return bodies[ :max( count, floor ) ]


def quick_smoke_test():
    """Build the corpus and report what it covers."""
    import cosa.utils.util as du

    du.print_banner( "dm_compression corpus_synth smoke test", prepend_nl=True )
    bodies = synth_corpus()
    print( f"  bodies            : {len( bodies )}" )
    print( f"  adversarial cases : {len( _ADVERSARIAL )} (first, so a slice keeps them)" )
    print( f"  literal kinds     : {len( _LITERALS )}" )
    print( f"  deterministic     : {synth_corpus() == bodies}" )


if __name__ == "__main__":
    quick_smoke_test()
