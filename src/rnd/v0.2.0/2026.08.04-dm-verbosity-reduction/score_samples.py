"""
Score a sample document on the two things the gate deliberately cannot see.
(María 🌸, 2026-08-11)

    python score_samples.py /tmp/dm-tutor-samples-*.md [...]

Reads the rendered documents, not the run — so it scores any arm, any run, and
scores two arms the same way. Give it several files and it prints one row each,
which is the comparison the ask-slot A/B needs.

WHY THIS IS SEPARATE FROM THE GATE. Two failures survive every structural check:

  1. **The ask is deleted.** Caught at 9-of-9 by reading, now gated. Re-checked
     here because a gate can be satisfied without the outcome being achieved —
     see 2.
  2. **The ask is bolted on.** "The question is: Are the markers present…" is a
     question by every mechanical test and a form being filled by any human one.
     The prompt says the ask must "stay a question"; the model satisfies that
     literally with a four-word prefix. **Any rule a model can satisfy on the
     surface, it will** — the same shape as the ratio instruction that moved
     51,854 tokens by 73.

⚠️ THIS SCORER IS A PROXY, NOT A JUDGE. Scaffolding is detected by a fixed list
of openers. A rewrite can be stilted in ways the list does not name, and a
listed opener can occasionally be the natural phrasing. It bounds the problem;
it does not settle it. Meaning-reversal and relocation remain invisible to it,
as they are to everything else we have — which is why Rick reads the pairs.
"""

import pathlib
import re
import sys

# The canned invitation the tutor appends. It is a question, and it is OURS —
# counting it as the surviving ask would let every rewrite pass by doing nothing.
CANNED_PS = "Need more detail? Ask me *one* question only!"

# Openers that announce a question instead of asking one. Deliberately short:
# a list that matches everything makes every rewrite look stilted, which is the
# same defect as a gate that fires on everything.
SCAFFOLDS = [
    "the question is",
    "the ask is",
    "my question is",
    "the open question is",
    "one question remains",
    "the remaining question is",
    "i would like to know",
    "please confirm whether",
    "the request is",
]


def pairs_from( path ):
    """
    Extract ( original, rewrite ) for every delivered sample in a document.

    Requires:
        - path names a sample document rendered by tutor_sample_run.py

    Ensures:
        - returns a list of ( original, rewrite ) string pairs
        - samples with no rewrite (failures) are skipped, because a failure has
          no phrasing to score — they are counted separately by the caller

    Raises:
        - nothing
    """
    text   = pathlib.Path( path ).read_text()
    blocks = re.split( r"\n## \d+\. ", text )[ 1: ]

    pairs = []
    for block in blocks:
        fenced = re.findall( r"```\n(.*?)\n```", block, re.S )
        if len( fenced ) >= 2: pairs.append( ( fenced[ 0 ], fenced[ 1 ] ) )
    return pairs


def strip_ps( rewrite ):
    """
    Remove the canned P.S. so it cannot answer for the model.

    Requires:
        - rewrite is a string

    Ensures:
        - returns the rewrite with the trailing canned invitation removed

    Raises:
        - nothing
    """
    index = rewrite.find( "P.S." )
    return rewrite[ :index ] if index != -1 and CANNED_PS in rewrite[ index: ] else rewrite


def score( path ):
    """
    Score one sample document.

    Requires:
        - path names a readable sample document

    Ensures:
        - returns a dict of counts; asked/kept/scaffolded are over DELIVERED
          rewrites only, since a failed rewrite has no ask to preserve

    Raises:
        - nothing
    """
    pairs = pairs_from( path )
    asked = kept = scaffolded = 0

    for original, rewrite in pairs:
        if "?" not in original: continue
        asked += 1

        body = strip_ps( rewrite )
        if "?" not in body: continue
        kept += 1

        # Look only at the sentence carrying the question — scaffolding elsewhere
        # is ordinary prose, not an announced ask.
        for sentence in re.split( r"(?<=[.!?])\s+", body ):
            if "?" not in sentence: continue
            lowered = sentence.strip().lower()
            if any( lowered.startswith( s ) or f" {s}" in lowered for s in SCAFFOLDS ):
                scaffolded += 1
            break

    return { "delivered" : len( pairs ), "asked" : asked, "kept" : kept, "scaffolded" : scaffolded }


def main():
    if len( sys.argv ) < 2:
        sys.exit( "usage: python score_samples.py <sample-doc.md> [more.md ...]" )

    print( f"{'document':<44}{'delivered':>10}{'asked':>7}{'ask kept':>10}{'bolted on':>11}" )
    for path in sys.argv[ 1: ]:
        s = score( path )
        kept_pct  = f"{s['kept']}/{s['asked']}"       if s[ "asked" ] else "—"
        scaf_pct  = f"{s['scaffolded']}/{s['kept']}"  if s[ "kept" ]  else "—"
        print( f"{pathlib.Path( path ).name:<44}{s['delivered']:>10}{s['asked']:>7}"
               f"{kept_pct:>10}{scaf_pct:>11}" )

    print()
    print( "ask kept  — the original asked something and the rewrite still asks (P.S. excluded)" )
    print( "bolted on — of those, how many ANNOUNCE the question rather than asking it" )
    print()
    print( "Neither column is a verdict. Meaning-reversal and relocation are invisible here." )


if __name__ == "__main__":
    main()
