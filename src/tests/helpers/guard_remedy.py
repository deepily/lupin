"""
Check a guard's REMEDY TEXT against reality — the shared half of a defect class.

THE CLASS (Tiberius 👑 `30ba7976` / `92445956`, Rio ⚡ `9350649d`, 2026-09-01)
----------------------------------------------------------------------------
Two of this repo's hook guards shipped a message that recommended the very hazard the
guard exists to prevent, found about an hour apart:

    stash_guard          told the reader `git checkout <sha> -- <path>` "touches
                         nothing shared, races nothing". False.
    commit_scope_guard   told the reader `git commit -F <file>` "parses cleanly and
                         gets reviewed". True of the flag alone, and incomplete: with a
                         heredoc still attached to the commit line it is not reviewed.

🔴 WHY THIS TEXT MATTERS MORE THAN A DOC. A guard's message is read by whoever JUST hit
the failure and is hunting for a way through. Wrong advice there is acted on
immediately. A doc is read once, by someone browsing.

TWO DIFFERENT ASSERTIONS, AND ONE DOES NOT IMPLY THE OTHER
----------------------------------------------------------
Both remedies above were perfectly legal commands. Legality is not the predicate.

    `remedy_is_readable`   the remedy WORKS — put it back through the guard's own
                           parser and the guard can act on it. Catches Rio's case,
                           where the recommended shape was still unreviewable.

    `remedy_carries_its_caveat`   the remedy is HONEST — a command that names a
                           hazardous operation carries that hazard's warning nearby.
                           Catches Tiberius's case, where the command ran fine and the
                           sentence around it was false.

⇒ A remedy can pass either one and fail the other. Assert the one your guard's message
actually claims, and reach for both when it claims both.

⚠️ THE HAZARD TABLE IS A FLOOR, NOT A DEFINITION. It lists operations THIS fleet has
been burned by, with the words that make them honest. It cannot know about a hazard
nobody has hit yet, so a green here means "carries the caveats we know to demand",
never "this advice is safe".
"""
import re


# How far from the hazard a caveat still counts, in LINES either side.
#
# 2 is not arbitrary and it is not measured-optimal: it is the distance that keeps a
# caveat on the following line, and the line after it, attached to its command — which
# is how the guard messages in this repo are actually written. Named rather than
# inlined so a caller can widen it for a differently-shaped message, and so the
# BOUNDARY is testable; test_guard_remedy_window_boundary.py exercises both sides.
CAVEAT_WINDOW_LINES = 2

# operation pattern -> at least one of these words must appear near it.
# Each entry is a hazard this fleet has measured, not a hazard imagined.
HAZARD_CAVEATS = {
    # Reverts to HEAD. In a shared checkout that DESTROYS a peer's uncommitted work,
    # and it moves no ref, so there is no reflog entry to recover from.
    r"git\s+checkout\b[^\n]*--\s": ( "overwrite", "reflog", "uncommitted", "last resort", "destroy" ),

    # A single repo-global stack shared by every worktree: every push races every pop.
    r"git\s+stash\b": ( "shared", "global", "races", "worktree" ),

    # ⚠️ `cp` from your own backup is NOT the safe form, and saying so was Tiberius's
    # correction to his own correction (92445956). It fixes WHICH BYTES come back; the
    # write is identical, so it still reverts a peer's edit made since your backup.
    r"\bcp\s+[^\n]*\.bak": ( "since", "peer", "still reverts", "backup is" ),

    # Clears the index. In this shared checkout that reaches a PEER'S staged work, and
    # merge_head_guard's squash remedy recommends a bare one while warning only that the
    # leftovers get re-swept by `git add -A`.
    #
    # ⚠️ NO LOOKAHEAD, DELIBERATELY. My first cut excluded `--hard`, on the reasoning
    # that the hard case is obviously destructive and already known. Tiberius 👑 and
    # Mr. Radio 🦉 both read it the other way and they are right: `--soft` clears staged
    # paths too, so an exclusion aimed at `--hard` lets the quieter form through
    # unqualified — and a floor that skips the variant people actually reach for is not
    # a floor. Every spelling of `git reset` names the index; every one wants the caveat.
    r"git\s+reset\b": ( "index", "peer", "staged", "re-stage" ),
}


def remedy_commands( text ):
    """
    The command lines a guard's message recommends.

    Requires:
        - text is the rendered message, not a format string

    Ensures:
        - returns the stripped INDENTED lines, which is how every guard in this repo
          sets off a command it wants copied
        - returns [] when the message recommends nothing — a caller asserting on a
          remedy must check for that itself rather than passing an empty list
        - never raises
    """
    return [ l.strip() for l in text.splitlines() if l.startswith( "  " ) and l.strip() ]


def remedy_is_readable( text, parse, prefix, substitutions=None ):
    """
    Every recommended command starting with `prefix` must be one `parse` can act on.

    Requires:
        - parse( command ) returns ( result, why ) — why is falsy when it succeeded,
          which is the shape both guards' pathspec parsers already use
        - prefix selects the commands this guard is responsible for reading

    Ensures:
        - returns the list of ( command, why ) for remedies the guard CANNOT read,
          empty when every one of them parses
        - raises when the message recommends no command matching `prefix` — a silent
          empty result would make a caller's assertion pass against a message it never
          actually read, which is the failure this whole module exists to catch
        - `substitutions` replaces placeholders like `<paths>` with something concrete
    """
    subs  = substitutions or {}
    found = [ c for c in remedy_commands( text ) if c.startswith( prefix ) ]
    assert found, (
        f"the message recommends no indented command starting with {prefix!r} — the "
        f"extraction is stale, and returning nothing here would make the caller's "
        f"assertion pass against a message it cannot read"
    )
    broken = []
    for command in found:
        concrete = command
        for placeholder, value in subs.items():
            concrete = concrete.replace( placeholder, value )
        _, why = parse( concrete )
        if why:
            broken.append( ( concrete, why ) )
    return broken


def remedy_carries_its_caveat( text, hazards=None, window=CAVEAT_WINDOW_LINES ):
    """
    A remedy naming a hazardous operation must carry that hazard's warning nearby.

    THE CASE THIS EXISTS FOR: stash_guard recommended `git checkout <sha> -- <path>`
    and called it safe. The command was legal and would have parsed anywhere — the
    defect was the sentence around it, so `remedy_is_readable` would have passed it.

    Requires:
        - text is the rendered message

    Ensures:
        - returns the list of ( matched_operation, required_words ) whose caveat words
          do not appear NEAR the hazard, empty when each hazard named is qualified
        - "near" is a WINDOW around the match — `window` lines either side, default
          CAVEAT_WINDOW_LINES —
          so a caveat on the following line still counts and one three paragraphs away
          does not
        - never raises — a message naming no hazard legitimately returns []

    🔴 THE WINDOW IS THE WHOLE POINT, AND THE FIRST CUT DID NOT HAVE IT. Searching the
    WHOLE message was written as deliberate ("a caveat one line below still reaches the
    reader") and it is too loose: a caveat word occurring anywhere passes the row, so a
    green said "these words are present somewhere", not "this command is qualified".
    Mr. Radio 🦉 named the mode; measured 2026-09-01 on a message whose `git checkout`
    remedy was entirely unqualified while the word "overwrite" appeared three
    paragraphs above about an unrelated queue — it PASSED. It fails now.

    ⚠️ A window is a heuristic, not a proof of association. It can still be fooled by a
    caveat that happens to sit near an unrelated hazard. It narrows the false positive;
    it does not close it, and this docstring says so rather than letting a green be read
    as more than it is.
    """
    table   = HAZARD_CAVEATS if hazards is None else hazards
    lines   = text.splitlines()
    missing = []
    for pattern, caveats in table.items():
        hits = [ i for i, line in enumerate( lines ) if re.search( pattern, line ) ]
        if not hits:
            continue
        # Qualified iff SOME occurrence carries its caveat nearby. One unqualified
        # mention alongside a qualified one is not the failure this looks for; a
        # hazard named ONLY without its caveat is.
        for i in hits:
            near = " ".join( lines[ max( 0, i - window ) : i + window + 1 ] ).lower()
            if any( word in near for word in caveats ):
                break
        else:
            missing.append( ( pattern, caveats ) )
    return missing
