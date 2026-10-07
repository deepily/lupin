#!/usr/bin/env python3
"""
Merge the repo's Claude Code hooks template into a settings file, or refuse and say why.

The installer used to replace the whole `hooks` key. A settings file that holds a hook the
template does not know lost it, with only a backup copy to show for it. This helper compares
the commands per event first and refuses when the settings hold one the template lacks.

Usage:
    merge_cc_hooks.py <settings.json> <template.json> [--force]

Exit codes:  0 written  ·  2 settings unreadable  ·  3 refused, unknown hook commands
"""
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

_INTERPRETER_RE = re.compile( r'^\s*(?:"[^"]*python3?"|\S*python3?)\s+' )
_DEFAULTED_RE   = re.compile( r"\$\{(\w+):-[^}]*\}" )


def normalise_command( command ):
    """
    Reduce a hook command to the part that names what it runs.

    Requires:
        - command is a str

    Ensures:
        - the leading interpreter (a quoted venv path, `python3`, `/usr/bin/python3`) is dropped
        - `${VAR:-default}` becomes `$VAR`, so a host-specific default does not make two
          spellings of one command look different
    """
    return _DEFAULTED_RE.sub( r"$\1", _INTERPRETER_RE.sub( "", command, count=1 ) ).strip()


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
    for event, entries in hooks.items():
        for entry in entries if isinstance( entries, list ) else [ ]:
            for hook in entry.get( "hooks", [ ] ) if isinstance( entry, dict ) else [ ]:
                if isinstance( hook, dict ) and hook.get( "command" ):
                    found.setdefault( event, [ ] ).append( hook[ "command" ] )
    return found


def unknown_commands( existing_hooks, template_hooks, allow=HOST_ONLY_HOOKS ):
    """
    The commands in `existing_hooks` that the template does not carry for the same event.

    Requires:
        - both arguments are `hooks` dicts; allow is a collection of normalised commands

    Ensures:
        - returns { event: [ raw command, ... ] }, empty when nothing would be lost
        - a command is known when its normalised form is in the template's set for that
          event, or in `allow`
    """
    known   = { event: { normalise_command( c ) for c in cmds } for event, cmds in commands_by_event( template_hooks ).items() }
    missing = { }
    for event, cmds in commands_by_event( existing_hooks ).items():
        for command in cmds:
            normal = normalise_command( command )
            if normal not in known.get( event, set() ) and normal not in allow:
                missing.setdefault( event, [ ] ).append( command )
    return missing


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
        - settings holding commands the template lacks: byte-identical, exit 3, the message
          names each one under its event, unless force
        - with force, or when nothing would be lost, a `.bak-<epoch>` copy is made first and
          only the `hooks` key is replaced; every other key is kept
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
    missing = unknown_commands( existing.get( "hooks", { } ) if isinstance( existing.get( "hooks" ), dict ) else { }, template_hooks, allow )
    if missing and not force:
        lines = [ f"  {event}: {command}" for event, commands in sorted( missing.items() ) for command in commands ]
        return EXIT_REFUSED, ( "settings hold hook commands the template does not know; left untouched.\n"
                               + "\n".join( lines )
                               + "\nAdd them to the template, or re-run with --force (a .bak copy is kept)." )
    if os.path.exists( settings_path ):
        stamp = int( ( now or time.time )() )
        shutil.copy2( settings_path, f"{settings_path}.bak-{stamp}" )
    existing[ "hooks" ] = template_hooks
    with open( settings_path, "w", encoding="utf-8" ) as handle:
        json.dump( existing, handle, indent=2 )
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
