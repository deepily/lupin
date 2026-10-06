"""
Shared DM text measurement: the one place a DM body's word count is computed.

The expression `len( body_text.split() )` used to be copied verbatim at four sites (`dm.py`
twice, `judge.py` and `judge_v2.py`). A `word_count_version` stamp on a corpus row means
nothing while four independent copies can silently drift. Centralizing the count here is what
makes that version stamp truthful.

Design: src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.04-dm-verbosity-pilot-plan.md
"""

# Bump this ONLY when dm_word_count's algorithm changes (e.g. a real tokenizer
# replaces whitespace splitting). Every experiment corpus row carries it so a later
# reader can tell which counting rule produced a given `words` value. It is a
# CONSTANT, not config: the count and its version travel together, in one place.
WORD_COUNT_VERSION = 1


def dm_word_count( text ):
    """
    Count words in a DM body by whitespace splitting.

    Requires:
        - text is a string (the caller-supplied DM body)

    Ensures:
        - returns len( text.split() ) — the whitespace-delimited token count
        - returns 0 for an empty or whitespace-only string
        - identical result to the four inline copies it replaces, so centralizing
          it changes no measured value (only where the value is computed)

    Raises:
        - AttributeError if text is not a string (fail loud — callers pass the
          already-validated DM body, never None)
    """
    return len( text.split() )
