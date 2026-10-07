#!/usr/bin/env python3
"""
Merge the repo's Claude Code hooks template into a settings file, or refuse and say why.

The installer used to replace the whole `hooks` key. A settings file that holds a hook the
template does not know lost it, with only a backup copy to show for it. This helper compares
whole entries per event first, matcher and every field included. It refuses when the settings
hold an entry the template does not carry exactly.

Usage:
    merge_cc_hooks.py <settings.json> <template.json> [--force]

Exit codes:  0 written  ·  2 settings unreadable  ·  3 refused, unknown hook commands
"""
import copy
import json
import os
import re
import shutil
import sys
import time

# Hook commands that exist on one host only and are meant to stay out of the template.
# It starts empty. A command named here is a ruling, not a convenience.
HOST_ONLY_HOOKS = frozenset()

EXIT_WRITTEN    = 0
EXIT_UNREADABLE = 2
EXIT_REFUSED    = 3

_INTERPRETER_RE = re.compile( r'^\s*(?:"[^"]*/python3?(?:\.\d+)?"|(?:\S*/)?python3?(?:\.\d+)?)\s+' )


def normalise_command( command ):
    """
    Drop the interpreter from a hook command, so two spellings of one script compare equal.

    Requires:
        - command is a str

    Ensures:
        - a leading python, python3 or python3.N, bare or by path, quoted or not, is dropped
        - nothing else changes: a variable with a default is not rewritten, because a live
          entry that differs from the template there is a difference worth refusing on
        - a program that merely ends in python, such as `/opt/mypython`, is kept
    """
    return _INTERPRETER_RE.sub( "", command, count=1 ).strip()


def normalise_entry( entry ):
    """
    Reduce one hook entry to a comparable string: its matcher and every field of every hook.

    Requires:
        - entry is an item of an event's list in a `hooks` key (normally a dict)

    Ensures:
        - returns a canonical JSON string, with each command normalised
        - two entries compare equal only when matcher, hook order and every other field
          (timeout and the rest) agree
        - an item that is not a dict compares as itself, so it never matches a template entry
    """
    if not isinstance( entry, dict ):
        return json.dumps( entry, sort_keys=True )
    canonical = dict( entry )
    if isinstance( entry.get( "hooks" ), list ):
        canonical[ "hooks" ] = [ _normalise_hook( hook ) for hook in entry[ "hooks" ] ]
    return json.dumps( canonical, sort_keys=True )


def _normalise_hook( hook ):
    """Return `hook` with its command normalised; other values pass through."""
    if isinstance( hook, dict ) and isinstance( hook.get( "command" ), str ):
        return { **hook, "command": normalise_command( hook[ "command" ] ) }
    return hook


def entries_by_event( hooks ):
    """
    List the entries of a `hooks` key, per event.

    Requires:
        - hooks is the dict under `hooks` in a settings file or a template

    Ensures:
        - returns { event: [ entry, ... ] } in file order; an event whose value is not a list is skipped
    """
    return { event: list( entries ) for event, entries in hooks.items() if isinstance( entries, list ) }


def commands_by_event( hooks ):
    """
    Collect the raw command strings of a `hooks` key, per event.

    Requires:
        - hooks is the dict under `hooks` in a settings file or a template

    Ensures:
        - returns { event: [ raw command, ... ] } in file order
        - ignores entries that are not dicts or carry no command
    """
    found = { }
    for event, entries in entries_by_event( hooks ).items():
        for entry in entries:
            for hook in entry.get( "hooks", [ ] ) if isinstance( entry, dict ) and isinstance( entry.get( "hooks" ), list ) else [ ]:
                if isinstance( hook, dict ) and hook.get( "command" ):
                    found.setdefault( event, [ ] ).append( hook[ "command" ] )
    return found


def _allowed( entry, allow ):
    """True when every hook of `entry` is named in `allow`; an empty entry is not allowed."""
    hooks = entry.get( "hooks" ) if isinstance( entry, dict ) else None
    return bool( hooks ) and isinstance( hooks, list ) and all(
        isinstance( hook, dict ) and normalise_command( str( hook.get( "command", "" ) ) ) in allow for hook in hooks )


def unknown_entries( existing_hooks, template_hooks, allow=HOST_ONLY_HOOKS ):
    """
    The entries in `existing_hooks` that the template does not carry exactly, per event.

    Requires:
        - both arguments are `hooks` dicts; allow is a collection of normalised commands

    Ensures:
        - returns { event: [ raw entry, ... ] }, empty when nothing would be lost or changed
        - an entry is known when its normalised form equals one of the template's entries for
          that event, so a different matcher, timeout or hook order makes it unknown
        - an entry made only of allow-listed commands is known
    """
    known   = { event: { normalise_entry( e ) for e in entries } for event, entries in entries_by_event( template_hooks ).items() }
    missing = { }
    for event, entries in entries_by_event( existing_hooks ).items():
        for entry in entries:
            if normalise_entry( entry ) not in known.get( event, set() ) and not _allowed( entry, allow ):
                missing.setdefault( event, [ ] ).append( entry )
    return missing


def _write_atomically( path, body ):
    """
    Write `body` as JSON to `path` through a temp file and a rename.

    Requires:
        - path is writable; body is JSON-serialisable

    Ensures:
        - an interruption leaves the old file whole, never a truncated one
        - the new file keeps the old file's mode when there was one
        - the temp file is removed when the write fails
    """
    temp = f"{path}.tmp-{os.getpid()}"
    try:
        with open( temp, "w", encoding="utf-8" ) as handle:
            json.dump( body, handle, indent=2 )
        if os.path.exists( path ):
            shutil.copymode( path, temp )
        os.replace( temp, path )
    except BaseException:
        if os.path.exists( temp ):
            os.remove( temp )
        raise


def merge( settings_path, template_path, force=False, allow=HOST_ONLY_HOOKS, now=None ):
    """
    Write the template's hooks into the settings file unless that would drop a hook.

    Requires:
        - template_path holds a JSON object with a `hooks` key
        - now is None (-> the clock) or a callable returning epoch seconds

    Ensures:
        - returns ( exit code, message )
        - settings missing: written fresh, exit 0
        - settings unreadable or not a JSON object: untouched, exit 2, unless force
        - settings holding an entry the template does not carry exactly (matcher, every field,
          normalised command): byte-identical, exit 3, the message prints each one under its
          event, unless force
        - with force, or when nothing would be lost, a `.bak-<epoch>` copy is made first and
          only the `hooks` key is replaced; every other key is kept, and so is any entry made
          only of allow-listed commands
    """
    with open( template_path, encoding="utf-8" ) as handle:
        template_hooks = json.load( handle )[ "hooks" ]
    existing = { }
    if os.path.exists( settings_path ):
        try:
            with open( settings_path, encoding="utf-8" ) as handle:
                existing = json.load( handle )
            if not isinstance( existing, dict ):
                raise ValueError( "not a JSON object" )
        except ( OSError, ValueError ) as error:
            if not force:
                return EXIT_UNREADABLE, f"settings file unreadable ({error}); left untouched, re-run with --force to replace it"
            existing = { }
    missing = unknown_entries( existing.get( "hooks", { } ) if isinstance( existing.get( "hooks" ), dict ) else { }, template_hooks, allow )
    if missing and not force:
        lines = [ f"  {event}: {json.dumps( entry )}" for event, entries in sorted( missing.items() ) for entry in entries ]
        return EXIT_REFUSED, ( "settings hold hook entries the template does not carry exactly; left untouched.\n"
                               + "\n".join( lines )
                               + "\nAdd or correct them in the template, or re-run with --force (a .bak copy is kept)." )
    if os.path.exists( settings_path ):
        stamp = int( ( now or time.time )() )
        shutil.copy2( settings_path, f"{settings_path}.bak-{stamp}" )
    merged = copy.deepcopy( template_hooks )
    if isinstance( existing.get( "hooks" ), dict ):
        for event, entries in entries_by_event( existing[ "hooks" ] ).items():
            for entry in entries:
                if _allowed( entry, allow ) and normalise_entry( entry ) not in { normalise_entry( e ) for e in merged.get( event, [ ] ) }:
                    merged.setdefault( event, [ ] ).append( entry )
    existing[ "hooks" ] = merged
    _write_atomically( settings_path, existing )
    return EXIT_WRITTEN, f"installed {len( template_hooks )} hook event-types -> {settings_path}"


def main( argv ):
    """
    Run the merge from the command line.

    Requires:
        - argv is [ settings, template ] or [ settings, template, "--force" ]

    Ensures:
        - prints the message to stdout on success and to stderr otherwise
        - returns the exit code
    """
    if len( argv ) not in ( 2, 3 ) or ( len( argv ) == 3 and argv[ 2 ] != "--force" ):
        print( "usage: merge_cc_hooks.py <settings.json> <template.json> [--force]", file=sys.stderr )
        return EXIT_UNREADABLE
    code, message = merge( argv[ 0 ], argv[ 1 ], force=len( argv ) == 3 )
    print( message, file=sys.stdout if code == EXIT_WRITTEN else sys.stderr )
    return code


if __name__ == "__main__":  # pragma: no cover - run as a subprocess by test_cli_exit_codes_and_streams
    sys.exit( main( sys.argv[ 1: ] ) )
