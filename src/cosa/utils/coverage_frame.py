"""
Assert that the coverage frame measures everything it claims to measure.

Why this exists: the `[tool.coverage.run]` comment in pyproject once claimed that
listing directory paths in `source` makes coverage walk the tree. The claim was
that coverage then enters every .py at 0%, which makes the baseline honest. It is
false in two ways:

  1. Coverage's unexecuted-file walk covers a source directory's top level only.
     It refuses to descend into a subdirectory that is not an import package
     (no `__init__.py`). Twelve files and 1,091 statements under src/scripts sat
     silently outside a path that reads as inclusive.
  2. Coverage skips any filename carrying a dot (or one of #~!$@%^&*()+=,) before
     the extension, as editor-junk protection. A file named like
     `probe-...-2026.05.12.py` is invisible for that reason and cannot join the
     frame without a rename. The mechanism matters more than that one file: a dot
     before the extension hides the next file for a reason unrelated to its contents.

Both were found by counting files, not by reading the config. The report listed
61 files where the disk held 74. A percentage cannot tell you about code it never
looked at, so a census is the only instrument that catches this.

The 13 files are not the issue. A frame can silently stop covering a directory,
and the number goes up when that happens, because unmeasured code is usually the
least-tested code. This module turns that into a test that fails.
"""

import json
import os
import fnmatch
import re
import tomllib

# coverage.files.find_python_files' own filter, mirrored here so this check
# predicts what coverage WILL skip rather than discovering it afterwards.
# Verified 2026-08-29 against a synthetic tree: "has-dashes.py" is INCLUDED at 0%,
# "dotted.name.2026.05.12.py" is NOT — dashes are fine, dots are not.
_COVERAGE_FILENAME_RE = re.compile( r"^[^.#~!$@%^&*()+=,]+\.pyw?$" )

# Files coverage cannot see and which we have deliberately decided not to rename.
# DECLARED, NOT HIDDEN: an omit would drop them from the denominator silently;
# naming them here keeps the frame's claim equal to its measurement, and the test
# fails if this list stops matching reality in either direction.
KNOWN_UNSEEABLE = {
    # Dated R&D prototype; src/cosa/rnd is the frame's only non-package directory.
    "src/cosa/rnd/2026.05.21-git-loc-delta-plot-prototype.py",
}


def coverage_can_see( path ):
    """
    Report whether coverage's unexecuted-file walk will consider this file.

    Requires:
        - path is a string path whose basename ends in .py or .pyw

    Ensures:
        - returns True iff the basename passes coverage's own filename filter
        - answers about the filename only; says nothing about the file's directory
    """
    return _COVERAGE_FILENAME_RE.match( os.path.basename( path ) ) is not None


def is_package_dir( dirpath ):
    """
    Report whether a directory is an import package.

    That decides whether coverage's walk will descend into it.

    Requires:
        - dirpath is a string path to an existing directory

    Ensures:
        - returns True iff dirpath contains an __init__.py
    """
    return os.path.isfile( os.path.join( dirpath, "__init__.py" ) )


def source_dirs( pyproject_text ):
    """
    Extract the coverage source directories from a pyproject.toml's text.

    It parses with tomllib, not a regex. A regex scan of the `source` block once
    returned two phrases from the block's own comments as if they were directories.
    A config reader must tell a comment from a value.

    Requires:
        - pyproject_text is the text of a pyproject.toml carrying a
          [tool.coverage.run] table with a `source` array

    Ensures:
        - returns the source entries in file order
        - raises ValueError if the table or the `source` array is absent
    """
    parsed = tomllib.loads( pyproject_text )
    try:
        return list( parsed[ "tool" ][ "coverage" ][ "run" ][ "source" ] )
    except KeyError as exc:
        raise ValueError( "pyproject.toml has no [tool.coverage.run] source array" ) from exc


def unreachable_declarations( unseeable_paths, declared=None ):
    """
    Return the declared-unseeable paths the census never reached.

    A declaration that never fires is worse than none: it is a receipt for a check
    that did not happen. This catches a renamed file, a moved directory, or a
    source entry dropped from pyproject.

    Requires:
        - unseeable_paths is the second return of unseen_python_files()
        - declared defaults to KNOWN_UNSEEABLE

    Ensures:
        - returns the sorted declared paths absent from unseeable_paths
        - an empty result means every declaration is doing work
        - reads nothing and writes nothing
    """
    # 🔴 A STRING IS ITERABLE, so `unreachable_declarations( "." )` would silently compare
    # against the CHARACTERS of that string and return a plausible non-empty answer —
    # exactly the shape this function exists to catch. Caught by Rio ⚡ within minutes of
    # the fix landing: he passed a root path, assuming this took one like its neighbours in
    # this module, and got the rnd path back. It looked like a finding. Refuse instead of
    # guessing what was meant; the failure must not be silent for the very defect the
    # function reports.
    if isinstance( unseeable_paths, str ):
        raise TypeError( "unseeable_paths must be the LIST from unseen_python_files(), not a "
                         "path string — a str would be compared character by character and "
                         f"return a plausible wrong answer (got {unseeable_paths!r})" )
    if isinstance( declared, str ):
        raise TypeError( f"declared must be a collection of paths, not a str (got {declared!r})" )
    if declared is None: declared = KNOWN_UNSEEABLE
    return sorted( set( declared ) - set( unseeable_paths ) )


def unseen_python_files( root, source_entries, reported_paths, omit_globs=() ):
    """
    Census the gap between the .py files a frame claims and a coverage report holds.

    Requires:
        - root is the repository root the source entries are relative to
        - source_entries is an iterable of repo-relative directory paths
        - reported_paths is an iterable of repo-relative paths present in a report
        - omit_globs is an iterable of coverage-style omit globs, read from
          pyproject by omit_patterns() rather than restated here

    Ensures:
        - returns ( unexpected, unseeable ) as two sorted lists of repo-relative paths
        - `unexpected` holds files coverage could see and the report does not carry;
          these are the defect, and each one is a directory the frame stopped covering
        - `unseeable` holds files coverage's filename filter rejects, which no source
          entry can recover; they are reported separately because the remedy is a
          rename, not a config change
        - a subdirectory is walked for the seen/unseen split only when its source
          entry is listed explicitly or it is an import package, mirroring coverage's
          own descent rule
        - an unseeable file is reported from a pruned directory too, because the
          descent rule governs what coverage can see, not what may be reported as
          invisible
    """
    reported   = set( reported_paths )
    omits      = tuple( omit_globs )
    unexpected = set()
    unseeable  = set()

    for entry in source_entries:
        abs_entry = os.path.join( root, entry )
        if not os.path.isdir( abs_entry ): continue
        for dirpath, dirnames, filenames in os.walk( abs_entry ):
            # Mirror coverage: below the top level, descend only into packages — for the
            # SEEN/UNSEEN split. But an UNSEEABLE file is reported even here (row f3400eab).
            #
            # 🔴 THE TWO GUARDS USED TO DEFER TO EACH OTHER AND LEAVE NOBODY LOOKING. A
            # dot-named .py ALONE in a non-package subdir escaped both: this walk pruned the
            # directory unread, and unreachable_subdirs() exempts a directory whose files are
            # all unseeable. Measured 2026-08-30 — a dated file alone in src/cosa/notes gave
            # unexpected=[], unseeable=[], orphans=[]; adding ONE dotless file beside it made
            # the orphan check fire. So the discriminator was "are ALL the .py in this
            # directory dot-named", and the live tree was in exactly that state: src/cosa/rnd
            # is neither package nor listed source, so KNOWN_UNSEEABLE declared a file this
            # census could never reach. A declaration that never fires is worse than none —
            # it is a receipt for a check that did not happen.
            #
            # The distinction that makes this correct rather than a widening: coverage's
            # descent rule governs what coverage CAN SEE, and therefore what may legitimately
            # be missing from a report. It says nothing about what we are permitted to REPORT
            # as invisible. An unseeable file is invisible wherever it sits, so reporting it
            # from a pruned directory cannot produce a false `unexpected` — the branch below
            # adds nothing to that list.
            if os.path.abspath( dirpath ) != os.path.abspath( abs_entry ) and not is_package_dir( dirpath ):
                dirnames[ : ] = []
                for filename in filenames:
                    if not filename.endswith( ( ".py", ".pyw" ) ):  continue
                    full = os.path.relpath( os.path.join( dirpath, filename ), root )
                    if is_omitted( full, omits ):                   continue
                    if not coverage_can_see( full ): unseeable.add( full )
                continue
            dirnames[ : ] = [ d for d in dirnames if d != "__pycache__" ]
            for filename in filenames:
                if not filename.endswith( ( ".py", ".pyw" ) ): continue
                full = os.path.relpath( os.path.join( dirpath, filename ), root )
                if is_omitted( full, omits ):           continue
                if full in reported:                    continue
                if coverage_can_see( full ): unexpected.add( full )
                else:                        unseeable.add( full )

    return sorted( unexpected ), sorted( unseeable )


def omit_patterns( pyproject_text ):
    """
    Extract the coverage omit globs from a pyproject.toml's text.

    The globs are read, never restated. A hard-coded copy of the omit list drifted
    from pyproject at once: it missed `*/cosa/agents/*/__main__.py` and an inline
    test file. Defining the frame in two places is the defect this module catches.

    Requires:
        - pyproject_text carries a [tool.coverage.run] table

    Ensures:
        - returns the omit entries in file order, or [] when none are configured
    """
    parsed = tomllib.loads( pyproject_text )
    try:
        return list( parsed[ "tool" ][ "coverage" ][ "run" ][ "omit" ] )
    except KeyError:
        return []


def is_omitted( path, patterns ):
    """
    Report whether a path is excluded by coverage's omit globs.

    Requires:
        - path is a repo-relative path
        - patterns is an iterable of coverage-style globs

    Ensures:
        - returns True iff the path matches any pattern, testing both the path as given
          and a "*/"-prefixed form, because coverage's globs are written to match the
          absolute paths it stores while this module works in repo-relative ones
    """
    return any( fnmatch.fnmatch( path, pat ) or fnmatch.fnmatch( "/" + path, pat )
                or fnmatch.fnmatch( path, pat.lstrip( "*/" ) ) for pat in patterns )


def unreachable_subdirs( root, source_entries, omit_globs=() ):
    """
    Find directories holding .py files that the configured frame cannot reach.

    This is the static form of the census. It needs no coverage run, so a unit-tier
    test can fail the moment someone adds a non-package subdirectory under a source
    entry. The dynamic census only tells you afterwards.

    Requires:
        - root is the repository root the source entries are relative to
        - source_entries is an iterable of repo-relative directory paths
        - omit_globs is an iterable of coverage-style omit globs from omit_patterns()

    Ensures:
        - returns a sorted list of repo-relative directory paths that hold at least
          one .py file coverage could see, are not import packages, and are not
          themselves listed in source_entries; every such directory would silently
          sit outside a frame that reads as inclusive
        - a directory nested inside a package chain is reachable and never returned
    """
    listed  = { os.path.normpath( e ) for e in source_entries }
    omits   = tuple( omit_globs )
    orphans = set()

    for entry in source_entries:
        abs_entry = os.path.join( root, entry )
        if not os.path.isdir( abs_entry ): continue
        for dirpath, dirnames, filenames in os.walk( abs_entry ):
            dirnames[ : ] = [ d for d in dirnames if d != "__pycache__" ]
            rel = os.path.normpath( os.path.relpath( dirpath, root ) )
            if rel in listed:            continue   # explicitly listed — reachable
            if is_package_dir( dirpath ): continue   # a package — coverage descends
            if is_omitted( rel + "/x.py", omits ): continue
            if any( f.endswith( ( ".py", ".pyw" ) ) and coverage_can_see( f ) for f in filenames ):
                orphans.add( rel )

    return sorted( orphans )


def report_paths( coverage_json_path ):
    """
    Read the file paths a coverage JSON report contains.

    Requires:
        - coverage_json_path names a file written by `coverage json`

    Ensures:
        - returns a sorted list of the report's file keys
    """
    with open( coverage_json_path, encoding="utf-8" ) as handle:
        return sorted( json.load( handle )[ "files" ] )
