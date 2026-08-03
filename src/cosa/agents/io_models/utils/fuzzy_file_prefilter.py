"""
Keyword pre-filter for fuzzy file matching.

Both the podcast-generator router path (`match_research_docs`) and the
runtime-argument-expeditor path (`_handle_fuzzy_file_match`) build a
`{ relative_path -> abs_path }` candidate map and hand it to a local LLM
(kaitchup/phi_4_14b) to pick the best match. A repo can hold thousands of
markdown files; sending them all overflows phi-4's 8k context and the request
fails with HTTP 400 before any description is judged.

This module is the single, shared narrowing step used by BOTH paths so there
is one behaviour instead of two: score each candidate path by keyword overlap
with the user's description and keep only the top matches.
"""

import cosa.utils.util as cu

# Filler words that carry no signal for matching. Voice transcriptions produce
# noisy descriptions ("no no no", filler words) — these are dropped before
# scoring so they cannot inflate a path's overlap count.
STOP_WORDS = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or",
    "my", "your", "that", "this", "it", "is", "was", "be", "can", "do",
    "no", "not", "if", "see", "find", "look", "get", "you", "me", "i",
    "about", "from", "with", "up", "out", "so", "just", "like", "also",
    "document", "file", "directory", "folder", "please", "could", "would",
}

# Upper bound on candidates handed to the LLM. Chosen to stay well inside the
# local model's context window.
MAX_CANDIDATES = 50


def prefilter_docs_map_by_keywords( docs_map, description, debug=False ):
    """
    Narrow a candidate document map to the top keyword-overlap matches.

    Requires:
        - docs_map is a dict mapping relative_path (str) -> abs_path (str)
        - description is a string

    Ensures:
        - returns a tuple ( result_map, arbitrary )
        - result_map's keys are a subset of docs_map's keys and NEVER exceed
          MAX_CANDIDATES entries — a HARD cap so the candidate list can never
          overflow the model's context regardless of the description
        - result_map IS docs_map (same object) exactly when docs_map already
          holds <= MAX_CANDIDATES entries; such a map is returned UNCHANGED and
          arbitrary is False (a within-budget list is complete, never a guess)
        - on a larger map with keyword overlap, keeps the highest-scoring
          MAX_CANDIDATES; arbitrary is False
        - on a larger map with NO scoring signal (no usable keywords, or zero
          keyword overlap), caps to a deterministic sorted MAX_CANDIDATES slice
          AND sets arbitrary True: the slice is unranked and may not contain the
          target, so the CALLER must NOT hand it to the model as a shortlist —
          it should ask the user for an exact path instead. Capping here still
          guarantees the no-overflow invariant for any caller that chooses to
          proceed with disclosure.
        - never returns None; never mutates the input

    Args:
        docs_map: candidate map { relative_path -> abs_path }
        description: user's natural-language description of the wanted file
        debug: enable debug output

    Returns:
        tuple ( dict, bool ): ( result_map, arbitrary ) — see Ensures.
    """
    # A map that already fits the model context needs no work — return it as-is.
    # This is complete, not a guess, so it is never 'arbitrary' and never bails,
    # even when the description shares no keyword with any path.
    if len( docs_map ) <= MAX_CANDIDATES:
        return docs_map, False

    # Extract keywords from description (lowered, de-duped, stopwords removed).
    desc_words = set(
        w for w in description.lower().replace( "-", " " ).replace( "/", " " ).replace( ".", " " ).replace( "&", "" ).split()
        if w not in STOP_WORDS and len( w ) > 2
    )

    if debug: print( f"[fuzzy_file_prefilter] Keywords extracted: {desc_words}" )

    # Score each path by keyword overlap against its path components.
    scored = []
    if desc_words:
        for rel_path in docs_map:
            path_lower = rel_path.lower().replace( "-", " " ).replace( "/", " " ).replace( "_", " " ).replace( ".", " " )
            path_words = set( path_lower.split() )
            score = len( desc_words & path_words )
            if score > 0:
                scored.append( ( score, rel_path ) )
        scored.sort( key=lambda x: x[ 0 ], reverse=True )

    if scored:
        keep = [ rel for _score, rel in scored[ :MAX_CANDIDATES ] ]
        if debug:
            print( f"[fuzzy_file_prefilter] Pre-filtered {len( docs_map )} → {len( keep )} candidates (top scores: {[ s for s, _ in scored[ :5 ] ]})" )
        return { k: docs_map[ k ] for k in keep }, False

    # No scoring signal (no usable keywords, or zero keyword overlap) on a LARGE
    # map. We MUST cap — returning the full map is the exact overflow that took
    # Lane 2 down — but a deterministic slice is UNRANKED and may not hold the
    # target, so we flag it arbitrary. The caller must ask for an exact path
    # rather than let the model pick confidently from a list that only looks
    # like a shortlist. (That confident-wrong pick is how a ham-radio report
    # once nearly went into the demo under a filename that looked right.)
    keep = sorted( docs_map.keys() )[ :MAX_CANDIDATES ]
    if debug:
        print( f"[fuzzy_file_prefilter] No scoring signal — hard-capping {len( docs_map )} → {len( keep )} (arbitrary slice; caller should ask for exact path)" )
    return { k: docs_map[ k ] for k in keep }, True


def quick_smoke_test():
    """Exercise the pre-filter across its behavioural branches."""
    cu.print_banner( "fuzzy_file_prefilter smoke test", prepend_nl=True )

    # Build a large map so the > MAX_CANDIDATES branch engages.
    big_map = { f"io/deep-research/x/2026.0{i%9+1}.01-topic-{i}.md": f"/abs/{i}.md" for i in range( 120 ) }
    big_map[ "io/deep-research/x/2026.07.25-the-kiss-protocol-brevity.md" ] = "/abs/kiss.md"

    try:
        # 1) Narrowing path — a specific description picks the KISS doc (not arbitrary).
        out, arbitrary = prefilter_docs_map_by_keywords( big_map, "the kiss brevity protocol", debug=True )
        assert len( out ) <= MAX_CANDIDATES, f"expected <= {MAX_CANDIDATES}, got {len( out )}"
        assert arbitrary is False, "keyword-scored narrowing is not arbitrary"
        assert "io/deep-research/x/2026.07.25-the-kiss-protocol-brevity.md" in out, "KISS doc should survive"
        print( "✓ narrowing keeps the keyword-matching doc" )

        # 2) Small map — returned unchanged, never arbitrary, even with zero overlap.
        small = { "io/a.md": "/abs/a.md", "io/b.md": "/abs/b.md" }
        out, arbitrary = prefilter_docs_map_by_keywords( small, "quantum zzz nomatch", debug=False )
        assert out is small and arbitrary is False, "small map must return unchanged, not arbitrary"
        print( "✓ small map returned unchanged (never bails)" )

        # 3) No usable keywords on a large map — hard-capped AND flagged arbitrary.
        out, arbitrary = prefilter_docs_map_by_keywords( big_map, "the a of it", debug=False )
        assert len( out ) == MAX_CANDIDATES and arbitrary is True, "keyword-less large map must cap + flag arbitrary"
        print( "✓ keyword-less large map hard-capped + arbitrary" )

        # 4) Zero overlap on a large map — hard-capped, deterministic, arbitrary.
        out, arbitrary = prefilter_docs_map_by_keywords( big_map, "quantum entanglement chromodynamics", debug=False )
        assert len( out ) == MAX_CANDIDATES and arbitrary is True, "zero-overlap large map must cap + flag arbitrary"
        assert list( out.keys() ) == sorted( big_map.keys() )[ :MAX_CANDIDATES ], "arbitrary slice must be deterministic"
        print( "✓ zero-overlap large map hard-capped (deterministic, arbitrary)" )

        print( "\n✓ ALL fuzzy_file_prefilter smoke tests passed" )
    except AssertionError as e:
        print( f"\n✗ smoke test FAILED: {e}" )
        raise


if __name__ == "__main__":
    quick_smoke_test()
