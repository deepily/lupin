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


def remedy_carries_its_caveat( text, hazards=None ):
    """
    A remedy naming a hazardous operation must carry that hazard's warning nearby.

    THE CASE THIS EXISTS FOR: stash_guard recommended `git checkout <sha> -- <path>`
    and called it safe. The command was legal and would have parsed anywhere — the
    defect was the sentence around it, so `remedy_is_readable` would have passed it.

    Requires:
        - text is the rendered message

    Ensures:
        - returns the list of ( matched_operation, required_words ) that appear WITHOUT
          any of their caveat words anywhere in the message, empty when each hazard
          named is also qualified
        - the search is over the WHOLE message, not the line: a caveat one line below
          its command still reaches the reader
        - never raises — a message naming no hazard legitimately returns []
    """
    table   = HAZARD_CAVEATS if hazards is None else hazards
    lowered = text.lower()
    missing = []
    for pattern, caveats in table.items():
        if not re.search( pattern, text ):
            continue
        if not any( word in lowered for word in caveats ):
            missing.append( ( pattern, caveats ) )
    return missing
