#!/usr/bin/env python3
"""
THE ONE PLACE THAT KNOWS WHERE THE FLEET-CAP KEY LIVES ON DISK — read and write.

🔴 WHY THIS IS A SURGICAL LINE EDIT AND NOT `configparser.write()`. The dial's key
lives in `src/conf/lupin-app.ini`, which is ~2,000 lines of heavily-commented,
column-aligned configuration. `ConfigParser.write()` round-trips the PARSED model:
it drops every comment, collapses the alignment and reorders nothing predictably.
Persisting one integer that way would destroy the file that documents it.

⇒ So the writer finds the ONE line defining the key and replaces the value on that
line, leaving every byte before and after it alone.

🔴 AND IT REFUSES RATHER THAN GUESSES. Three outcomes, and only one of them writes:

    · the key is defined EXACTLY ONCE  -> edit that line
    · the key is defined NOWHERE       -> refuse, naming the key and the file
    · the key is defined MORE THAN ONCE -> refuse, naming every line

The third is the one worth spelling out. Sections inherit (`[Lupin: Development]`
inherits `[Lupin: Baseline]`), so two definitions means the value a reader gets
depends on which block it loaded — and a writer that picked one would be writing to
a key half the fleet does not read. A tool facing a job it cannot finish declines the
whole operation and says what it did not do; it does not write to its best guess and
return something the caller reads as success.

⚠️ THE WRITE IS ATOMIC. Temp file in the same directory, then `os.replace`, which is
atomic on POSIX within one filesystem. A crash mid-write must not leave the
configuration file truncated — every process in the fleet reads it at boot.

🔴 AND WHY A FRESH READ EXISTS AT ALL, WHICH IS THE HALF THAT MAKES THE DIAL GOVERN
SOMETHING. `ConfigurationManager` is a process-lifetime singleton (the `@singleton`
decorator caches the instance) with no mtime check and no reload path. The cap is
enforced in the HOST MCP process, which is long-running. So a browser write reaches
the file and the enforcing process keeps its boot-time value until it restarts — a
dial that changes nothing until a bounce, which is the exact defect that held this
slider in the first place.

⇒ `read_cap_from_disk` parses the file at CALL time so the spawn path sees the number
the operator just set. It is deliberately NOT a second source of truth: it reads the
same key in the same file the configuration manager loaded, just later.

⚠️ COST, SAID OUT LOUD: this parses the INI on every gate call. That is the SPAWN
path — measured in spawns per hour, not per second — so a few milliseconds there buys
a cap that is honest. If this ever moves onto a hot path, cache it on mtime; do not
silently drop the freshness.
"""
import os
import re
import tempfile

from lupin_mcp import config_write_lock
from typing import List, NamedTuple, Optional, Tuple


class KeyNotFound( Exception ):
    """The key has no definition in the file. Raised rather than defaulted — see below."""


class KeyDefinedTwice( Exception ):
    """The key is defined more than once. NAMES EVERY LINE; never picks one."""


class Definition( NamedTuple ):
    """Where a key is defined: 0-based line index, its section, and the raw line."""
    index   : int
    section : str
    line    : str


def _section_of( lines: List[ str ], upto: int ) -> str:
    """The most recent `[section]` header at or above line `upto`, or "" if none."""
    for i in range( upto, -1, -1 ):
        stripped = lines[ i ].strip()
        if stripped.startswith( "[" ) and stripped.endswith( "]" ):
            return stripped[ 1:-1 ]
    return ""


def _key_pattern( key: str ) -> "re.Pattern":
    """
    Match a line DEFINING `key` — the key at column 0, then padding, then `=`.

    ⚠️ ANCHORED AT THE START OF THE LINE AND NOT SEARCHED ANYWHERE ELSE, because
    the same words appear in this file's own comments describing the key. A search
    that matched a comment would count a definition that does not exist and trip
    the duplicate refusal on a file that is perfectly well-formed.
    """
    return re.compile( r"^" + re.escape( key ) + r"([ \t]*)=(.*)$" )


def find_definitions( lines: List[ str ], key: str ) -> List[ Definition ]:
    """
    Every line defining `key`, in file order.

    Requires:
        - lines is the file split on newlines, comments included
        - key is the INI key exactly as written

    Ensures:
        - returns one Definition per DEFINING line (comments never match)
        - returns [] when the key is not defined
        - never raises
    """
    pattern = _key_pattern( key )
    found   = []
    for i, line in enumerate( lines ):
        if pattern.match( line ):
            found.append( Definition( index=i, section=_section_of( lines, i ), line=line ) )
    return found


DEFAULT_BLOCK = "Lupin: Development"
BLOCK_ENV     = "LUPIN_CONFIG_MGR_CLI_ARGS"


def active_block( environ=None ) -> str:
    """
    The configuration block this process loaded.

    Requires:
        - environ is a mapping, or None for the process environment

    Ensures:
        - returns the config_block_id the process's LUPIN_CONFIG_MGR_CLI_ARGS names, with "+" read as a space
        - returns DEFAULT_BLOCK when the variable is absent or names no block, so the host reads the development block
    """
    args = ( os.environ if environ is None else environ ).get( BLOCK_ENV, "" )
    for part in args.split():
        if part.startswith( "config_block_id=" ) and part.split( "=", 1 )[ 1 ]: return part.split( "=", 1 )[ 1 ].replace( "+", " " )
    return DEFAULT_BLOCK


def inherit_chain( lines: List[ str ], block: str ) -> List[ str ]:
    """
    The block and every block it inherits from, nearest first.

    Requires:
        - lines is the file split on newlines; block is a section name without brackets

    Ensures:
        - returns [ block, its parent, its grandparent, ... ] following each section's `inherits =` line
        - stops at a section with no inherits line, and never repeats a section, so a cycle ends
    """
    chain = []
    while block and block not in chain:
        chain.append( block )
        start = next( ( i for i, line in enumerate( lines ) if line.strip() == f"[{block}]" ), None )
        block = ""
        for line in lines[ start + 1: ] if start is not None else []:
            if line.strip().startswith( "[" ): break
            if re.match( r"^inherits[ \t]*=", line ):
                block = line.split( "=", 1 )[ 1 ].strip()
                break
    return chain


def pick_definition( lines: List[ str ], found: List[ Definition ], block: Optional[ str ] = None ) -> Optional[ Definition ]:
    """
    The one definition the active block reads, or None when the file leaves it ambiguous.

    Requires:
        - found is find_definitions( lines, key ) for one key

    Ensures:
        - returns the sole definition when there is exactly one, whatever its section
        - with several, returns the one in the nearest section of the active block's inherit chain, so a VM-only override beats the base
        - returns None when none of them is in that chain, or the nearest section defines the key twice
    """
    if len( found ) == 1: return found[ 0 ]
    for section in inherit_chain( lines, active_block() if block is None else block ):
        here = [ d for d in found if d.section == section ]
        if here: return here[ 0 ] if len( here ) == 1 else None
    return None


def locate_key( path: str, key: str ) -> Definition:
    """
    The ONE line defining `key`, or a refusal naming exactly what stopped it.

    Requires:
        - path names a readable INI file

    Ensures:
        - returns the sole Definition when the key is defined exactly once, or the one the active block reads (see pick_definition)
        - raises KeyNotFound when it is defined nowhere, naming key and file
        - raises KeyDefinedTwice when defined more than once, naming EVERY
          section and line number

    🔴 THE DUPLICATE CASE REFUSES, AND THAT IS THE WHOLE POINT OF THIS FUNCTION.
    Configuration blocks inherit, so two definitions of one key means the value a
    process gets depends on which block it loaded. A writer that picked one would
    be writing to a key half the fleet does not read — and would return a
    perfectly plausible success while the enforced number never moved.
    """
    with open( path, "r", encoding="utf-8" ) as handle:
        lines = handle.read().split( "\n" )

    found = find_definitions( lines, key )

    if not found:
        raise KeyNotFound(
            f"Refusing to act: the key `{key}` is defined NOWHERE in {path}. "
            f"Nothing was written. Add the key to the configuration file first — "
            f"this writer edits an existing definition and never invents one, "
            f"because the section it landed in would decide which processes read it."
        )
    chosen = pick_definition( lines, found )
    if chosen is not None: return chosen
    where = "; ".join( f"[{d.section}] line {d.index + 1}" for d in found )
    raise KeyDefinedTwice(
        f"Refusing to write: the key `{key}` is defined {len( found )} times in "
        f"{path} — {where}, and none of them is in the block this process loaded "
        f"({active_block()}) or one it inherits from, or that block defines it twice. Nothing was written. "
        f"Keep one definition in the base block and at most one override in a block that inherits from it."
    )


def read_value_from_disk( path: str, key: str ) -> Optional[ str ]:
    """
    The key's value, parsed FRESH from the file at call time.

    Ensures:
        - returns the raw value string (stripped of surrounding whitespace and any
          trailing inline comment is NOT stripped — INI values here carry none)
        - returns None when the file is unreadable, or the key is absent, or the
          key is defined more than once
        - NEVER raises

    ⚠️ AMBIGUITY READS AS ABSENT HERE, WHERE IT REFUSES IN THE WRITER, and the
    asymmetry is deliberate. This runs on the SPAWN path: a fail-soft None falls
    back to the configuration manager, which is exactly the behaviour that existed
    before this module. The writer, by contrast, is a deliberate operator action
    with a human waiting on the answer — there, silence would be a lie.
    """
    try:
        with open( path, "r", encoding="utf-8" ) as handle:
            lines = handle.read().split( "\n" )
    except OSError:
        return None
    chosen = pick_definition( lines, find_definitions( lines, key ) )
    if chosen is None:
        return None
    match = _key_pattern( key ).match( chosen.line )
    return match.group( 2 ).strip() if match else None


def read_int_from_disk( path: str, key: str ) -> Optional[ int ]:
    """
    `read_value_from_disk` coerced to int, or None when absent or not an integer.

    Ensures:
        - never raises; a non-integer value reads as None so the caller falls back
    """
    raw = read_value_from_disk( path, key )
    if raw is None:
        return None
    try:
        return int( raw )
    except ValueError:
        return None


def _replace_value_line( path: str, key: str, value_text: str, insert_after: Optional[ str ] = None ) -> None:
    """
    Replace the value on the one line that defines `key`, atomically, under the write lock.

    Requires:
        - path names a writable configuration file
        - key is defined in it exactly once
        - value_text is the text to put after the equals sign
        - insert_after is a key defined exactly once, or None

    Ensures:
        - when the key is absent and insert_after is given, the line is added after that
          key's line, aligned to the same column
        - the defining line keeps its key and its column alignment
        - every other byte in the file is unchanged
        - the replacement is a temp file in the same folder moved in with os.replace
        - nothing is written when the key is missing or defined twice
        - the temp file is removed when the replacement fails

    Raises:
        - KeyNotFound or KeyDefinedTwice without writing anything
        - OSError when the lock or the replacement fails
    """
    with config_write_lock.write_lock():
        try:
            definition = locate_key( path, key )      # refuses before touching anything
        except KeyNotFound:
            if insert_after is None:
                raise
            definition = None

        with open( path, "r", encoding="utf-8" ) as handle:
            content = handle.read()
        lines = content.split( "\n" )

        if definition is not None:
            match   = _key_pattern( key ).match( lines[ definition.index ] )
            padding = match.group( 1 )                # preserve the column alignment
            lines[ definition.index ] = f"{key}{padding}= {value_text}"
        else:
            anchor  = locate_key( path, insert_after )
            column  = lines[ anchor.index ].index( "=" )
            padding = " " * max( 1, column - len( key ) )
            lines.insert( anchor.index + 1, f"{key}{padding}= {value_text}" )

        directory = os.path.dirname( os.path.abspath( path ) ) or "."
        handle_fd, temp_path = tempfile.mkstemp( dir=directory, prefix=".fleet-cap-", suffix=".ini" )
        try:
            with os.fdopen( handle_fd, "w", encoding="utf-8" ) as temp:
                temp.write( "\n".join( lines ) )
                temp.flush()
                os.fsync( temp.fileno() )
            os.chmod( temp_path, 0o644 )
            os.replace( temp_path, path )
        except BaseException:
            try:
                os.unlink( temp_path )
            except OSError:
                pass
            raise


def write_int_to_disk( path: str, key: str, value: int ) -> int:
    """
    Replace the key's value in place, atomically, and return what the file now says.

    Requires:
        - path names a writable INI file
        - key is defined in it exactly once
        - value is an int

    Ensures:
        - only the value after the equals sign changes
        - the replacement is atomic and taken under the write lock
        - returns the value re-read from the file, never the argument
        - raises KeyNotFound or KeyDefinedTwice without writing anything

    The return is a re-read and not the input. A writer that echoes its argument reports
    success the same way whether the bytes reached the disk or not. The re-read goes through
    the production parser, so a write that lands where the reader cannot see it fails here.
    """
    _replace_value_line( path, key, str( int( value ) ) )
    persisted = read_int_from_disk( path, key )
    if persisted is None:
        raise KeyNotFound(
            f"Wrote `{key}` to {path} and could not read it back as an integer. "
            f"The file was replaced; its state is on disk and should be inspected."
        )
    return persisted


def write_bool_to_disk( path: str, key: str, value: bool, insert_after: Optional[ str ] = None ) -> bool:
    """
    Replace the key's value with true or false in place, and return what the file now says.

    Requires:
        - path names a writable INI file
        - key is defined in it exactly once
        - value is a bool
        - insert_after is a key defined exactly once, or None

    Ensures:
        - writes the text true or false and nothing else
        - adds the line after insert_after's line when the key is absent and insert_after is
          given, and refuses an absent key when it is not
        - the replacement is atomic and taken under the write lock
        - returns the value re-read from the file, never the argument
        - raises KeyNotFound or KeyDefinedTwice without writing anything
    """
    _replace_value_line( path, key, "true" if value else "false", insert_after=insert_after )
    raw = read_value_from_disk( path, key )
    if raw is None:
        raise KeyNotFound(
            f"Wrote `{key}` to {path} and could not read it back. "
            f"The file was replaced; its state is on disk and should be inspected."
        )
    return raw.strip().lower() == "true"
