"""
Assert that the coverage FRAME measures everything it claims to measure.

WHY THIS EXISTS (row e2099400, 2026-08-29). pyproject's `[tool.coverage.run]`
comment asserted that listing DIRECTORY PATHS in `source` makes coverage "walk
the tree and enter every .py at 0%, which is what makes the baseline honest."
Measured on 2026-08-29, that is FALSE in two ways, and both were live:

  1. coverage's unexecuted-file walk covers a source directory's TOP LEVEL only.
     It refuses to descend into a subdirectory that is not an import package
     (no `__init__.py`). Twelve files / 1,091 statements under src/scripts were
     silently outside a path that reads as inclusive.
  2. coverage skips any filename carrying a dot (or one of #~!$@%^&*()+=,) before
     the extension — editor-junk protection. `probe-cc-bounded-billing-2026.05.12.py`
     was invisible for that reason and could not be brought into the frame without
     renaming it; it was renamed to `probe_cc_bounded_billing.py` on 2026-08-30
     (row 9078a035) and is now measured.

Both were found by counting files, not by reading the config: the report listed
61 files where the disk held 74. A percentage cannot tell you about code it never
looked at, so the only instrument that catches this is a census.

⇒ THE POINT IS NOT THE 13 FILES. It is that a frame can silently stop covering a
directory, and the number goes UP when that happens, because unmeasured code is
usually the least-tested code. This module turns that into a test that fails.
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
        - returns True iff the BASENAME passes coverage's own filename filter
        - answers about the filename ONLY; says nothing about the file's directory
    """
    return _COVERAGE_FILENAME_RE.match( os.path.basename( path ) ) is not None


def is_package_dir( dirpath ):
    """
    Report whether a directory is an import package, which is what decides
    whether coverage's walk will descend into it.

    Requires:
        - dirpath is a string path to an existing directory

    Ensures:
        - returns True iff dirpath contains an __init__.py
    """
    return os.path.isfile( os.path.join( dirpath, "__init__.py" ) )


def source_dirs( pyproject_text ):
    """
    Extract the coverage source directories from a pyproject.toml's text.

    ⚠️ PARSED WITH tomllib, NOT A REGEX. The first version of this scanned the
    `source = [ ... ]` block for quoted strings and dutifully returned two phrases
    out of the block's own COMMENTS ("so coverage can target it", "enter every .py
    at 0%") as if they were directories. On a row about instruments that mis-read
    what they measure, a config reader that cannot tell a comment from a value is
    not a detail — so the parsing is delegated to the TOML parser.

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
    Declared-unseeable paths the census never reached.

    🔴 A DECLARATION THAT NEVER FIRES IS WORSE THAN NO DECLARATION — it is a receipt for a
    check that did not happen. Found by Rio ⚡ 2026-08-30 (row f3400eab): the live tree
    reported `unseeable == []` while KNOWN_UNSEEABLE named a file, so the entry read as
    "handled" when nothing had looked. The walk fix in unseen_python_files is what makes the
    entry fire; this is what stops the same silence returning by another route — a renamed
    file, a moved directory, or a source entry dropped from pyproject.

    Requires:
        - unseeable_paths is the second return of unseen_python_files()
        - declared defaults to KNOWN_UNSEEABLE

    Ensures:
        - returns the sorted declared paths ABSENT from unseeable_paths
        - an empty result means every declaration is doing work
        - reads nothing and writes nothing
    """
    if declared is None: declared = KNOWN_UNSEEABLE
    return sorted( set( declared ) - set( unseeable_paths ) )


def unseen_python_files( root, source_entries, reported_paths, omit_globs=() ):
    """
    Census the gap between the .py files a frame CLAIMS and the files a coverage
    report actually contains.

    Requires:
        - root is the repository root the source entries are relative to
        - source_entries is an iterable of repo-relative directory paths
        - reported_paths is an iterable of repo-relative paths present in a report
        - omit_globs is an iterable of coverage-style omit globs, READ FROM
          pyproject by omit_patterns() rather than restated here

    Ensures:
        - returns ( unexpected, unseeable ) as two sorted lists of repo-relative paths
        - `unexpected` holds files coverage COULD see and the report does not carry —
          these are the defect, and each one is a directory the frame stopped covering
        - `unseeable` holds files coverage's filename filter rejects, which no source
          entry can recover; they are reported separately because the remedy is a
          rename, not a config change
        - a subdirectory is walked for the SEEN/UNSEEN split ONLY when its source entry
          is listed explicitly or it is an import package, mirroring coverage's own
          descent rule — but an UNSEEABLE file is reported from a pruned directory too
          (row f3400eab), because the descent rule governs what coverage CAN SEE, not
          what may be reported as invisible
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

    ⚠️ READ, NEVER RE-STATED. The first version of the gate hard-coded its own list of
    omitted substrings, and it had ALREADY drifted from pyproject's `omit` when it was
    first run — it missed `*/cosa/agents/*/__main__.py` and the one inline test file, so
    the frame check reported two files as unaccounted that the frame deliberately omits.
    A frame defined in two places is the defect this module exists to catch; defining the
    omissions twice is the same mistake one level down.

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
    Find directories holding .py files that the configured frame CANNOT reach.

    This is the static form of the census, and it is the one that matters: it needs
    no coverage run, so it can guard the frame in the unit tier and fail the moment
    somebody adds a non-package subdirectory under a source entry. The dynamic
    census only tells you afterwards, on a report somebody has to remember to read.

    Requires:
        - root is the repository root the source entries are relative to
        - source_entries is an iterable of repo-relative directory paths
        - omit_globs is an iterable of coverage-style omit globs from omit_patterns()

    Ensures:
        - returns a sorted list of repo-relative directory paths that hold at least
          one .py file coverage could see, are NOT import packages, and are NOT
          themselves listed in source_entries — i.e. every directory whose files
          would silently sit outside a frame that reads as inclusive
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
