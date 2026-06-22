#!/usr/bin/env python3
"""
Centralized persona-name normalization — THE single source of truth.

Persona/voice names that carry accents or punctuation ("María", "Mr. Radio")
were historically slugged by a different ad-hoc algorithm in every subsystem,
so the same persona keyed as "maría" / "maria" / "mr. radio" / "mr radio" /
"mrradio" depending on which code touched it. That drift produced the
2026-06-18 heartbeat false-idle P0 (owed-oracle queried "maría", store held
"maria", zero rows matched) and the 2026-06-11 arbiter role misclassification.

This module collapses every persona-string transform onto ONE root with two
thin, documented derivations. The decision rule for callers:

    - STRUCTURED IDENTITY  (store write/query, comparing two persona values,
      dict keys, role-roster membership)            -> canonical_persona_key
    - NOISY FREE-TEXT INPUT (resolve a human-typed/spoken reference to a pool
      name)                                          -> normalize_for_match
    - FILENAME / DM-TOPIC / SESSION NAME             -> persona_slug

`lupin_mcp` is the one package importable by both `cosa` (server, arbiter) and
`lupin_cli` (hooks), so it is the natural shared home. This module is
stdlib-only (re, unicodedata) and imports nothing from the project, so it is
safe to import in hook subprocesses and cannot create an import cycle.

Origin: `canonical_persona_key` was first introduced at
`lupin_cli/claude_code/hooks/lib/session_bridge.py` (2026-06-18, READ-seam
fix) and is moved here verbatim; `session_bridge` and `commons_persona_matcher`
re-export from this module for backward compatibility.

R&D: src/rnd/v0.1.9/2026.06.19-persona-name-normalization/01-centralized-persona-normalization-plan.md
"""
import re
import unicodedata


def canonical_persona_key( name ) -> str:
    """
    Canonical persona key for cross-seam task-store matching — the IDENTITY root.

    THE single normalizer the owed-work READ seam, the task-store WRITE seam, the
    arbiter role-matcher, and every persona comparison must agree on, so a
    persona's `owner_persona` rows are ALWAYS found regardless of which surface
    spelled the name. The store holds names in the form the voice pool defines —
    accent-stripped + punctuation-stripped + lowercased, INTERNAL SPACES KEPT
    (display "María" -> "maria", "Mr. Radio" -> "mr radio"). This mirrors that
    transform and is IDEMPOTENT, so it is safe whether the caller passes the
    display form ("María") or the already-normalized pool form ("maria"). Its
    output EQUALS the store key, so it doubles as a query parameter.

    Drift history (the bug this kills): the READ seam previously used a bare
    `.lower()`, so a persona whose name carried an accent/period ("María",
    "Mr. Radio") queried "maría"/"mr. radio" and matched ZERO of the store's
    "maria"/"mr radio" rows -> false "nothing owed".

    Requires:
        - name is a string or None

    Ensures:
        - None / non-string / empty / whitespace-only -> "" (unmatchable sentinel)
        - otherwise: NFKD-decomposed, combining marks dropped, lowercased,
          reduced to [a-z0-9 ] (punctuation/emoji removed, single spaces kept),
          internal runs of whitespace collapsed to one space, ends trimmed
        - IDEMPOTENT: canonical_persona_key( canonical_persona_key( x ) ) == canonical_persona_key( x )

    Args:
        name: A persona name in display or already-normalized form

    Returns:
        str: the canonical store key
    """
    if not name or not isinstance( name, str ):
        return ""
    decomposed = unicodedata.normalize( "NFKD", name )
    ascii_only = "".join( c for c in decomposed if not unicodedata.combining( c ) )
    stripped   = re.sub( r"[^a-z0-9 ]", "", ascii_only.lower() )
    return re.sub( r"\s+", " ", stripped ).strip()


def normalize_for_match( name ) -> str:
    """
    Lenient free-text match key — the IDENTITY root with internal spaces removed.

    For resolving a NOISY human-supplied persona reference (typed or spoken) to a
    pool name, where the speaker may drop the space ("mrradio") or vary
    punctuation/case ("MR.RADIO"). Defined as `canonical_persona_key` with spaces
    stripped, so it shares the exact accent/punctuation/case rules of the root and
    can never drift from it. Note this is STRICTLY MORE lenient than the identity
    key and is therefore NOT a valid store key — use `canonical_persona_key` for
    anything that touches `owner_persona`.

    This also FIXES the prior `_normalize_for_match`, which kept accents
    ("María" -> "maría") and so disagreed with the store on accented names;
    routing through the root makes it accent-correct ("María" -> "maria").

    Requires:
        - name is a string or None

    Ensures:
        - None / non-string / empty / all-punctuation -> ""
        - "Mr. Radio" / "mr radio" / "mrradio" / "MR.RADIO" all -> "mrradio"
        - "María" -> "maria"
        - IDEMPOTENT

    Args:
        name: A persona reference in any human-entered form

    Returns:
        str: the space-free lenient match key
    """
    return canonical_persona_key( name ).replace( " ", "" )


def persona_slug( name, sep="-" ) -> str:
    """
    Filesystem- / topic- / session-name-safe slug — the IDENTITY root with
    internal spaces replaced by a separator.

    For building DM-topic names, session names, and filenames from a persona.
    Shares the root's accent/punctuation/case rules (so it is accent-proof,
    unlike the prior inline `re.sub` sluggers), differing only in the final
    space->separator substitution.

    Idempotency (bug 9980dd9a): `canonical_persona_key` strips ALL punctuation,
    including the separator itself, so naively re-slugging an already-slugged
    value FUSES its words — `persona_slug( "mr-radio", "-" )` would key as
    "mrradio" and return "mrradio", losing the word boundary and breaking the
    round-trip. The fix substitutes `sep` back to a space BEFORE
    canonicalization, so a boundary a prior slug encoded as `sep` survives the
    punctuation strip and re-slugging reproduces the original. Holds for any
    single fixed `sep` a caller round-trips through (e.g. "-" and "_").

    Requires:
        - name is a string or None
        - sep is a string (typically "-" or "_")

    Ensures:
        - None / non-string / empty / all-punctuation -> ""
        - "Mr. Radio" -> "mr" + sep + "radio" (e.g. "mr-radio" or "mr_radio")
        - "María" -> "maria"
        - IDEMPOTENT for a fixed sep:
              persona_slug( persona_slug( x, sep ), sep ) == persona_slug( x, sep )

    Args:
        name: A persona name in display or already-normalized form
        sep:  Separator to substitute for internal spaces (default "-")

    Returns:
        str: the slug, or "" for unusable input
    """
    # Restore word boundaries a prior slug encoded as `sep` so re-slugging
    # round-trips (canonical_persona_key would otherwise drop `sep` as punctuation).
    if isinstance( name, str ) and sep:
        name = name.replace( sep, " " )
    key = canonical_persona_key( name )
    return key.replace( " ", sep ) if key else ""


def quick_smoke_test():
    """Non-destructive smoke test for the three persona-normalization primitives."""
    import cosa.utils.util as du

    du.print_banner( "persona_normalization smoke test", prepend_nl=True )

    ok = True

    # canonical_persona_key — the identity root (keep internal spaces).
    key_cases = [
        ( "María",        "maria"    ),
        ( "Mr. Radio",    "mr radio" ),
        ( "Mr.  Radio 🦉", "mr radio" ),
        ( "  María  ",    "maria"    ),
        ( "Tiberius",     "tiberius" ),
        ( None,           ""         ),
        ( 123,            ""         ),
        ( "!!! ...",      ""         ),
    ]
    for raw, want in key_cases:
        got = canonical_persona_key( raw )
        flag = "✓" if got == want else "✗"
        if got != want: ok = False
        print( f"  {flag} canonical_persona_key( {raw!r} ) = {got!r} (want {want!r})" )
    # idempotence
    for already in ( "maria", "mr radio", "tiberius" ):
        if canonical_persona_key( already ) != already: ok = False

    # normalize_for_match — lenient (drop spaces), now accent-correct.
    match_cases = [
        ( "Mr. Radio", "mrradio" ),
        ( "mr radio",  "mrradio" ),
        ( "MR.RADIO",  "mrradio" ),
        ( "María",     "maria"   ),
        ( "",          ""        ),
    ]
    for raw, want in match_cases:
        got = normalize_for_match( raw )
        flag = "✓" if got == want else "✗"
        if got != want: ok = False
        print( f"  {flag} normalize_for_match( {raw!r} ) = {got!r} (want {want!r})" )

    # persona_slug — filesystem/topic safe.
    slug_cases = [
        ( "Mr. Radio", "-", "mr-radio" ),
        ( "Mr. Radio", "_", "mr_radio" ),
        ( "María",     "-", "maria"    ),
        ( None,        "-", ""         ),
    ]
    for raw, sep, want in slug_cases:
        got = persona_slug( raw, sep=sep )
        flag = "✓" if got == want else "✗"
        if got != want: ok = False
        print( f"  {flag} persona_slug( {raw!r}, sep={sep!r} ) = {got!r} (want {want!r})" )

    print()
    print( "✓ persona_normalization smoke test PASSED" if ok else "✗ persona_normalization smoke test FAILED" )


if __name__ == "__main__":
    quick_smoke_test()
