"""
A synthetic DM corpus for the freeze property tests — deterministic, in-repo, no artifact.

WHY THIS EXISTS. The six corpus tests in `test_freeze.py` read a 4 MB snapshot of REAL
fleet DM traffic from `src/tmp/`, which is gitignored. Present, the module reported 494
passed; absent, 488 passed and 6 skipped — both reading as success, with `git status`
structurally unable to say which run you got. Mr. Radio ruled 2026-08-30 that the real
snapshot NEVER goes in the repo: 2,951 real message bodies and two dozen personal email
addresses do not belong in a public tree, and this repo's own secret scanner cannot read
`.jsonl` at all, so it could not vouch for them either.

🔴 THE POINT IS THAT A CORPUS IN CODE CANNOT GO MISSING. Replacing one gitignored file
with a committed file would fix this instance; generating the bodies in a committed module
ends the class. No path to check, no artifact to forget, and no second mode in which the
same suite measures less and still says "passed".

WHAT THESE TESTS ACTUALLY DISCRIMINATE ON — and why plausible chatter is the wrong target.
All six are PROPERTY tests: freeze/restore round-trips, placeholder tokens never colliding
with source text, the validator's verdict not depending on a span's label, resolved spans
never overlapping, no unrestored placeholder reaching delivery, and `compress_or_original`
never raising. None cares whether the text reads like a real conversation. What they need
is text that strains the SPAN EXTRACTOR: every pattern kind, and the awkward arrangements
— nesting, adjacency, and literals sitting on each other's boundaries.

🔴 WHAT THIS DOES NOT COVER — READ BEFORE TRUSTING A GREEN FROM IT.
· It exercises the kinds THIS FILE KNOWS TO BUILD. The coverage test derives the kind list
  from `freeze._PATTERNS` at runtime, so a NEW pattern added to freeze.py reddens instead
  of being silently unexercised. That guard is why the coverage claim is checkable — it is
  not a claim that the ARRANGEMENTS are exhaustive. They are not, and cannot be.
· It cannot produce the thing that made real traffic valuable: combinations nobody designed.
  Both defects recorded in `test_freeze.py`'s own comments were found because real text did
  something unexpected. A generator written by the same person who wrote the checks cannot
  supply that, and this file must not be described as if it does.
· It is not a statistical model of fleet traffic. Lengths and shapes here stress the
  extractor; they do not resemble how anyone writes.

⇒ Read a green here as "the invariants hold on adversarial text we thought of", never as
"the invariants hold on real traffic". The second claim needs real traffic, and real
traffic is not going in this repo.

DETERMINISM. `synth_corpus()` takes an explicit seed and returns the same bodies every
call, so a failure is reproducible from the seed alone and two machines cannot disagree
about what the suite measured.
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
        - the SAME seed always yields the SAME bodies, so a failure is reproducible from
          the seed alone
        - every kind in `_LITERALS` appears somewhere in the result
        - the adversarial cases come FIRST, so a truncated slice (`corpus[ :300 ]`, which
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
