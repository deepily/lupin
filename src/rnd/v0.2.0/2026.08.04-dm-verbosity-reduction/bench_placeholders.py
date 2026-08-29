"""
Placeholder token-cost benchmark for arm 4 Phase 1.

Answers the expert review's issue 5: "character length says nothing about
token cost." Measures each candidate placeholder format against real
tokenizers, in context (not in isolation), because BPE merges across the
boundary between a placeholder and its neighbouring prose.

Requires:
    - tiktoken importable with cached encodings (no network)

Ensures:
    - reports tokens per placeholder for every candidate, in and out of context
    - reports the delta against the literals the placeholders replace
"""

import tiktoken

# Candidates. The plan proposes the first; the rest are the alternatives
# worth pricing before the format is locked.
CANDIDATES = {
    "plan ⟦L00⟧"        : "⟦L00⟧",
    "review ⟦S02_PATH00⟧": "⟦S02_PATH00⟧",
    "ascii [[L00]]"      : "[[L00]]",
    "ascii §L00§"        : "§L00§",
    "ascii <L00>"        : "<L00>",
    "ascii {L00}"        : "{L00}",
    "ascii @L00@"        : "@L00@",
    "ascii __L00__"      : "__L00__",
    "ascii #L00#"        : "#L00#",
    "bare L00"           : "L00",
    "bare X00"           : "X00",
    "private L00": "L00",
}

# Real literals from the corpus, for the "what did we replace" baseline.
LITERALS = [
    "judge.py:572",
    "d256e25a",
    "/var/lupin/io/deep-research",
    ":7999",
    "2026-08-06",
    "max_tokens=8192",
]

CONTEXTS = [
    "The leak is at {} , shipped in a hurry.",
    "Fix {} before Thursday.",
    "See {}.",
    "({})",
    "Row {} is committed.",
]


def measure( encoder, text ):
    return len( encoder.encode( text ) )


def main():
    for encoding_name in ( "cl100k_base", "o200k_base" ):
        try:
            encoder = tiktoken.get_encoding( encoding_name )
        except Exception as error:
            print( f"\n{encoding_name}: unavailable ({type( error ).__name__})" )
            continue

        print( f"\n{'='*74}\n{encoding_name}\n{'='*74}" )
        print( f"{'candidate':26s} {'alone':>6s} {'in-ctx avg':>11s} {'worst ctx':>10s}" )
        print( "-" * 74 )

        rows = []
        for label, placeholder in CANDIDATES.items():
            alone = measure( encoder, placeholder )
            # In context: cost of the sentence with the placeholder, minus the
            # cost of the same sentence with the slot empty. This captures
            # merges across the boundary, which measuring alone misses.
            deltas = []
            for template in CONTEXTS:
                with_ph = measure( encoder, template.format( placeholder ) )
                without = measure( encoder, template.format( "" ) )
                deltas.append( with_ph - without )
            rows.append( ( sum( deltas ) / len( deltas ), label, alone, max( deltas ) ) )

        for average, label, alone, worst in sorted( rows ):
            print( f"{label:26s} {alone:6d} {average:11.1f} {worst:10d}" )

        print( f"\n{'literal being replaced':38s} {'tokens':>7s}" )
        print( "-" * 74 )
        for literal in LITERALS:
            print( f"{literal:38s} {measure( encoder, literal ):7d}" )


if __name__ == "__main__":
    main()
