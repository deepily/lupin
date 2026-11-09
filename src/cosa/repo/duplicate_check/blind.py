"""Blindness: strip what tells the judge which arm wrote a definition; refuse what remains."""
import hashlib
import re

from cosa.repo.duplicate_check import errors as err

REUSE_TOOL_TOKENS = ( "check_exists", "fetch_similar", "read_capability", "record_search", "reuse-reviewer", "reuse-receipt", "SEARCHED" )
COMMENT_STARTS    = { "py": ( "#", ), "ts": ( "//", "/*", "*" ) }
WORKTREE_PREFIX   = re.compile( r"^(?:[^/]+/)*?\.claude/worktrees/[^/]+/" )
PLACEHOLDER       = "TOOLNAME"      # stands for a reuse-tool name left in a definition; it holds no scrub token itself


def _check_scrub( scrub ):
    """
    Refuse a scrub list that is empty-handed or holds an empty token.

    Requires:
        - scrub is an iterable of strings

    Ensures:
        - returns the tokens as a list

    Raises:
        - ValueError if a token is empty, since an empty token is found in every text
    """
    tokens = list( scrub )
    if "" in tokens: raise ValueError( "the scrub list holds an empty token" )
    return tokens


def scrub_tokens( arm_labels ):
    """
    Build the scrub list: the reuse-tool tokens plus the arm labels the harness writes.

    Requires:
        - arm_labels is an iterable of the label strings the run harness writes; it has no default because the strings
          are read from the harness's arm configuration at freeze time

    Ensures:
        - returns the tool tokens followed by the labels, each once
        - holds no ordinary word

    Raises:
        - ValueError if a label is empty
    """
    tokens = list( REUSE_TOOL_TOKENS )
    for label in _check_scrub( arm_labels ):
        if label not in tokens: tokens.append( label )
    return tokens


def assert_blind( text, scrub ):
    """
    Refuse text that still carries a scrub token.

    Requires:
        - text is a string bound for the judge
        - scrub is the scrub list

    Ensures:
        - returns None when no token occurs in text; the match is on the exact characters and the case of the token

    Raises:
        - DuplicateCheckError BLINDNESS_BREACH naming each token found, never the text around it
        - ValueError if the scrub list holds an empty token
    """
    found = [ token for token in _check_scrub( scrub ) if token in text ]
    if found: raise err.DuplicateCheckError( err.BLINDNESS_BREACH, f"scrub tokens survive in text bound for the judge: {', '.join( found )}" )


def relative_path( file ):
    """
    Drop a worktree prefix from a path, so a worktree's name never reaches the judge.

    Requires:
        - file is a posix path, relative to some root

    Ensures:
        - a path that runs through .claude/worktrees/<name>/ loses everything up to and including that folder
        - every other path is returned unchanged
    """
    return WORKTREE_PREFIX.sub( "", file, count=1 )


def opaque_id( d ):
    """
    Return the id the judge sees: "x-" and ten hex digits over path, name and text.

    Requires:
        - d is a definition record from extract

    Ensures:
        - the origin is not an input, so the id says nothing about which side wrote the definition
        - two definitions that differ only in a worktree prefix of the path have the same id
    """
    return "x-" + hashlib.sha256( "\0".join( ( relative_path( d[ "file" ] ), d[ "name" ], d[ "text" ] ) ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def strip_comment_lines( text, lang, scrub ):
    """
    Remove every whole comment line that holds a scrub token.

    Requires:
        - text is the source of one definition; lang is "py" or "ts"
        - scrub is the scrub list

    Ensures:
        - a line is a comment line when, left-trimmed, it starts with the comment marker of its language
        - a comment line without a token is kept, and so is every line that is not a comment line
        - a token in a trailing comment, a string or code is left alone for assert_blind to refuse

    Raises:
        - KeyError if lang is neither "py" nor "ts"
    """
    starts = COMMENT_STARTS[ lang ]
    tokens = _check_scrub( scrub )
    return "\n".join( line for line in text.split( "\n" ) if not ( line.lstrip().startswith( starts ) and any( t in line for t in tokens ) ) )


def redact_tool_names( text, scrub ):
    """
    Replace every reuse-tool name left in a text with the placeholder word `TOOLNAME`.

    Requires:
        - text is a string; scrub is the scrub list

    Ensures:
        - returns text with each occurrence of each tool-name token that is in scrub replaced, the longest first so a name that holds another leaves no fragment
        - arm labels and any other scrub token are left alone, so assert_blind still refuses them
        - a text with no tool name is returned unchanged

    Raises:
        - ValueError if the scrub list holds an empty token
    """
    names = sorted( [ t for t in _check_scrub( scrub ) if t in REUSE_TOOL_TOKENS ], key=len, reverse=True )
    for name in names: text = text.replace( name, PLACEHOLDER )
    return text


def blind_definition( d, scrub, redact_tools=False ):
    """
    Return what the judge may see of a definition.

    Requires:
        - d is a definition record from extract
        - scrub is the scrub list; redact_tools is True to replace reuse-tool names left in the fields by the placeholder word

    Ensures:
        - returns { id, lang, file, name, sig, text } and nothing else, so origin, line numbers, calls and declared names stay out
        - id is opaque_id, computed from the original text; file has no worktree prefix; text has lost its comment lines that hold a scrub token
        - with redact_tools, a tool name left in file, name, sig or text is replaced by the placeholder word, so a definition that names a reuse tool is still judged; without it the name is a breach
        - no field carries a scrub token

    Raises:
        - DuplicateCheckError BLINDNESS_BREACH if a token survives in any field, an arm label with redact_tools too
    """
    show    = ( lambda t: redact_tool_names( t, scrub ) ) if redact_tools else ( lambda t: t )
    blinded = { "id": opaque_id( d ), "lang": d[ "lang" ], "file": show( relative_path( d[ "file" ] ) ), "name": show( d[ "name" ] ), "sig": show( d[ "sig" ] ),
                "text": show( strip_comment_lines( d[ "text" ], d[ "lang" ], scrub ) ) }
    assert_blind( "\n".join( ( blinded[ "file" ], blinded[ "name" ], blinded[ "sig" ], blinded[ "text" ] ) ), scrub )
    return blinded


def breaching_ids( defs, scrub, redact_tools=False ):
    """
    Name the definitions that blind_definition would refuse.

    Requires:
        - defs are definition records from extract; scrub is the scrub list; redact_tools is blind_definition's flag

    Ensures:
        - returns the sorted ids of the definitions whose blinding raises, which it does only for BLINDNESS_BREACH
        - nothing is blinded for use; this only asks the same question blind_definition answers
    """
    found = set()
    for d in defs:
        try:
            blind_definition( d, scrub, redact_tools )
        except err.DuplicateCheckError:
            found.add( d[ "id" ] )
    return sorted( found )


def candidate_order( blinded ):
    """
    Order blinded definitions by the sha of their opaque ids, so position tells nothing.

    Requires:
        - blinded is a list of records from blind_definition

    Ensures:
        - returns a new list, ordered by the sha256 of each id
        - the same set of definitions gives the same order whatever order they arrive in
    """
    return sorted( blinded, key=lambda b: hashlib.sha256( b[ "id" ].encode( "utf-8" ) ).hexdigest() )
