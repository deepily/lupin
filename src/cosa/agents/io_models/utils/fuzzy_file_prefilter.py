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

# A scored shortlist is trusted as a complete narrowing only when its BEST
# candidate shares at least this many keyword tokens with the description. A top
# overlap of exactly one is a single incidental hit — a best-of-list guess that a
# zero-overlap target could plausibly beat — so it is flagged arbitrary and the
# caller asks for an exact path rather than trusting a shortlist the target may
# never have entered (row 888711f0). This is a DIFFERENT lever than MAX_CANDIDATES:
# widening the cap only moves the threshold; this removes the silence for thin
# matches by turning a weak narrowing into a visible ask.
MIN_TRUSTWORTHY_TOP_SCORE = 2


def _extract_keywords( description ):
    """
    Lower-case, split, and drop stopwords + short tokens → a keyword set.

    The single tokenizer shared by the prefilter and the deterministic
    dominant-match check so both narrow on IDENTICAL keyword rules.

    Requires:
        - description is a string

    Ensures:
        - returns a set of lower-cased tokens (len > 2, not in STOP_WORDS)
        - never returns None; never raises on empty input

    Args:
        description: user's natural-language description

    Returns:
        set[str]: the signal-bearing keywords
    """
    return set(
        w for w in description.lower().replace( "-", " " ).replace( "/", " " ).replace( ".", " " ).replace( "&", "" ).split()
        if w not in STOP_WORDS and len( w ) > 2
    )


def _score_docs_by_keyword_overlap( docs_map, desc_words ):
    """
    Score each candidate path by keyword overlap with the description.

    Requires:
        - docs_map maps relative_path (str) -> abs_path (str)
        - desc_words is a set of keywords (may be empty)

    Ensures:
        - returns a list of ( score, rel_path ) for paths with score > 0,
          sorted by score DESCENDING
        - returns [] when desc_words is empty or nothing overlaps
        - never mutates docs_map

    Args:
        docs_map: candidate map { relative_path -> abs_path }
        desc_words: keyword set from _extract_keywords

    Returns:
        list[ tuple[ int, str ] ]: scored, non-zero, sorted desc
    """
    scored = []
    if desc_words:
        for rel_path in docs_map:
            path_lower = rel_path.lower().replace( "-", " " ).replace( "/", " " ).replace( "_", " " ).replace( ".", " " )
            path_words = set( path_lower.split() )
            score = len( desc_words & path_words )
            if score > 0:
                scored.append( ( score, rel_path ) )
        scored.sort( key=lambda x: x[ 0 ], reverse=True )
    return scored


def dominant_keyword_match( docs_map, description ):
    """
    Return the ONE rel-path whose keyword overlap dominates, else None.

    Deterministic pre-empt of the nondeterministic phi-4 pick (row 8e70a34d):
    at <= MAX_CANDIDATES the prefilter is a pass-through, so today EVERY
    candidate reaches the LLM and the LLM makes the choice. When exactly one
    candidate holds a strictly-unique top keyword-overlap score, the description
    already names that document — resolve it without the model. A TIE at the top
    is genuine ambiguity: return None and let the LLM decide, exactly as before.

    Requires:
        - docs_map maps relative_path (str) -> abs_path (str)
        - description is a string

    Ensures:
        - returns a rel_path KEY of docs_map when its overlap score is strictly
          greater than every other candidate's AND that score > 0
        - returns None on no keyword signal, zero overlap, or a top-score tie
        - never mutates docs_map

    Args:
        docs_map: candidate map { relative_path -> abs_path }
        description: user's natural-language description of the wanted file

    Returns:
        str or None: the dominant rel_path, or None when ambiguous.
    """
    scored = _score_docs_by_keyword_overlap( docs_map, _extract_keywords( description ) )
    if not scored: return None
    top_score = scored[ 0 ][ 0 ]
    winners   = [ rel for score, rel in scored if score == top_score ]
    if len( winners ) == 1: return winners[ 0 ]
    return None


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
          MAX_CANDIDATES; arbitrary is False ONLY when the whole scored list fit
          (nothing scored dropped) AND the top overlap score is a genuine
          multi-token match (>= MIN_TRUSTWORTHY_TOP_SCORE). arbitrary is True when
          the scored list exceeds MAX_CANDIDATES — a real match may sit past the
          cut (row c143fd84) — OR when the top score is thin (a single incidental
          keyword hit): a zero-overlap target could beat a best-of-list-of-one, so
          the shortlist it was dropped from is not trustworthy (row 888711f0)
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
    desc_words = _extract_keywords( description )

    if debug: print( f"[fuzzy_file_prefilter] Keywords extracted: {desc_words}" )

    # Score each path by keyword overlap against its path components.
    scored = _score_docs_by_keyword_overlap( docs_map, desc_words )

    if scored:
        # A scored narrowing on a LARGE map ALWAYS drops the zero-overlap
        # candidates — they never enter `scored` — and a target that shares no
        # keyword token with the description scores zero, so it is dropped
        # silently. Two conditions make the shortlist untrustworthy (arbitrary):
        #   (1) TRUNCATION — more scored candidates than the cap, so a genuinely
        #       scored target may rank past the cut (row c143fd84); or
        #   (2) a THIN top score — the best path shares only ONE keyword token
        #       with the description. A single incidental hit is best-of-list,
        #       not a reliable narrowing, and a zero-overlap target could well be
        #       the real one, so the caller must ask rather than trust the
        #       shortlist (row 888711f0). A top score at or above
        #       MIN_TRUSTWORTHY_TOP_SCORE is a genuine multi-token match and
        #       stays trustworthy, preserving the c143fd84 narrowing benefit.
        truncated = len( scored ) > MAX_CANDIDATES
        top_score = scored[ 0 ][ 0 ]
        thin      = top_score < MIN_TRUSTWORTHY_TOP_SCORE
        arbitrary = truncated or thin
        keep = [ rel for _score, rel in scored[ :MAX_CANDIDATES ] ]
        if debug:
            print( f"[fuzzy_file_prefilter] Pre-filtered {len( docs_map )} → {len( keep )} candidates (top scores: {[ s for s, _ in scored[ :5 ] ]}; truncated={truncated}; thin={thin})" )
        return { k: docs_map[ k ] for k in keep }, arbitrary

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

        # 5) Thin partial signal — only a single incidental keyword hit scores; a
        #    zero-overlap target could be the real one, so the shortlist is a
        #    best-of-list guess and must be flagged arbitrary (row 888711f0).
        thin_map = { f"io/x/unrelated-{i}.md": f"/abs/{i}.md" for i in range( MAX_CANDIDATES + 10 ) }
        thin_map[ "io/x/widget-summary.md" ] = "/abs/widget.md"
        out, arbitrary = prefilter_docs_map_by_keywords( thin_map, "widget", debug=False )
        assert arbitrary is True, "a single incidental keyword hit must flag arbitrary"
        print( "✓ thin single-keyword narrowing flagged arbitrary" )

        print( "\n✓ ALL fuzzy_file_prefilter smoke tests passed" )
    except AssertionError as e:
        print( f"\n✗ smoke test FAILED: {e}" )
        raise


if __name__ == "__main__":
    quick_smoke_test()
