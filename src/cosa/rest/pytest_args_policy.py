"""
Allowlist policy for caller-supplied pytest arguments (row 60f04102).

THE DEFECT THIS CLOSES: `POST /api/test-suite/submit` accepts a free-form
`pytest_args` string, shlex-parses it, and hands the tokens to
`subprocess.Popen( [ "bash", script_path ] + args )` with only `--bg` stripped
(job.py:1134, :1184). There is no `shell=True`, so shell metacharacters are NOT
the vector and a metacharacter denylist would buy nothing — that was this
author's first proposed control, and Maria refuted it before it was written.

THE ACTUAL VECTOR, and it needs no shell at all: **pytest imports every path it
is asked to collect.** A caller who can put an arbitrary path into `pytest_args`
gets that file imported by the runner, as the server's OS user, with no sandbox
and no import allowlist. `pytest /tmp/evil.py` is arbitrary code execution
spelled as a test run.

=> THE CONTROL IS AN ALLOWLIST, NOT A DENYLIST. Every token must be a flag this
policy recognises, a value bound to a flag that takes one, or a test path that
resolves inside a permitted test root. Anything else is refused. A denylist has
to anticipate the attack; an allowlist only has to enumerate the legitimate
surface, which is small and already known — the flag sets below come from a
census of every `pytest_args` usage in the tree.

WHERE THIS IS ENFORCED, and the ordering is Maria's call, not a preference:
**job build is the authoritative point**, because every path into execution runs
through it — HTTP submits, jobs rehydrated from persistence
(job_persistence.py:765), and side channels such as capture-bounce-resubmit.py.
A submit-only check would leave all of those unguarded. The router calls the
same function so a bad request is refused at the door with a clear 400, but that
is USABILITY; it is not the control. One function serves both so the two cannot
drift apart.

WHAT THIS POLICY DELIBERATELY DOES NOT DO: it does not decide WHO may submit.
That is a role question and genuinely separate. Admin is very likely the wrong
grain — every seat account holds `['user']`, so an admin gate would lock out the
only legitimate submitter — and that decision belongs to Rick, not here. This
module is the control that holds even for a caller who is authorised and wrong.
"""

import os
import shlex


# ---- The legitimate surface -------------------------------------------------
# Sources: a census of every pytest_args usage in the tree, plus the per-suite
# INI keys at lupin-app.ini:2097-2102. Adding a flag here is a deliberate act;
# a flag absent from these sets is refused, which is the point.

# Flags that stand alone and take no value.
ALLOWED_BARE_FLAGS = {
    "-v", "-vv", "-vvv", "-q", "-qq", "-x", "-s", "-l",
    "--verbose", "--quiet", "--exitfirst", "--no-header",
    "--bg",                     # stripped downstream; harmless to accept here
    "--auto-proxy", "--no-confirm", "--update-snapshots", "--include-opus",
    "--all", "--fail-fast", "--continue-on-failure", "--dry-run",
    "--collect-only", "--co", "--lf", "--ff", "--strict-markers",
}

# Flags that take a value, either as `--flag=value` or as two tokens.
# For -k / -m the value is matched against collected test NAMES and is never
# executed or opened, so free text is safe there.
ALLOWED_VALUE_FLAGS = {
    # For -k / -m the value is matched against collected test NAMES and is never
    # imported or opened, so free text is safe there.
    "-k", "-m",
    "--maxfail", "--tb",
    "--cost-cap-usd", "--group", "--scenario-id", "--durations",
    "--timeout", "--log-cli-level",
    # Path-valued, and therefore ALSO in PATH_VALUE_FLAGS below. They must be
    # listed here too or they are refused outright rather than confined — which
    # is exactly what happened on the first run of the attack probe, and would
    # have broken the two real --deselect and three real --ignore usages in the
    # tree. A flag that is confined but not recognised is not a stricter guard,
    # it is a broken one.
    "--deselect", "--ignore",
}

# ---- Flags deliberately NOT allowed, and why ---------------------------------
# Recorded rather than merely omitted, because the next person to widen this
# allowlist needs to know these were considered and refused on purpose.
#
#   -p / --plugin  ARBITRARY CODE EXECUTION. `-p <module>` makes pytest IMPORT
#                  that module before collection. It is not a path, so path
#                  confinement never applies to it. This author originally had
#                  -p in the allowlist above; Maria found it and it was proven
#                  live — `pytest -p evil_plugin --collect-only` executed the
#                  module body and wrote a file, as uid 1001, straight through
#                  the guard that exists to prevent exactly that. There is no
#                  caller-legitimate use of -p in this repo's census.
#
#   --junit-xml    A caller-controlled WRITE path. Confining it to the test
#   --junitxml     roots does not make it safe — that is where the source lives,
#                  so a caller could overwrite src/tests/conftest.py, which
#                  pytest imports on the next run. The job appends its own
#                  --junit-xml at job.py:1180 AFTER validation, so nothing
#                  legitimate needs the caller to supply one.
#
#   --rootdir      Relocates pytest's config discovery, which changes which
#                  conftest.py is imported.
#
#   -n             xdist worker count. Harmless in itself, but absent from the
#                  census; it can be added deliberately if something needs it.
#
# THE SHAPE OF BOTH REAL HOLES: a flag whose VALUE is a module name or a write
# target rather than a read path. Path confinement does not reach either one.
# Before adding any flag here, ask what its value NAMES — not whether it looks
# dangerous.

# Value-taking flags whose value IS a filesystem path and must be confined.
# NOTE these are all READ paths. --junit-xml was here and has been removed: it is
# a WRITE path, and confinement to the test roots would have licensed overwriting
# src/tests/conftest.py rather than preventing it.
PATH_VALUE_FLAGS = { "--deselect", "--ignore" }

# Test roots a caller-supplied path may resolve inside, relative to project root.
ALLOWED_TEST_ROOTS = ( "src/tests", "src/cosa/tests" )

# A single argument longer than this is refused outright. Nothing in the census
# came close; an enormous token is a smell, not a test selector.
MAX_ARG_LENGTH = 512
MAX_ARG_COUNT  = 64


class PytestArgsRejected( ValueError ):
    """Raised when caller-supplied pytest args fail the allowlist."""
    pass


def _flag_name( token ):
    """
    Ensures:
        - "--tb=short" -> "--tb";  "-k" -> "-k";  "src/tests/x.py" -> None
        - never raises
    """
    if not token.startswith( "-" ): return None
    return token.split( "=", 1 )[ 0 ]


def _path_is_confined( raw_path, project_root ):
    """
    Requires:
        - raw_path is a caller token, possibly carrying a `::nodeid` suffix
        - project_root is an absolute path to the repository root

    Ensures:
        - returns True iff the path portion resolves inside one of
          ALLOWED_TEST_ROOTS after symlink and `..` resolution
        - an absolute path outside those roots returns False
        - traversal ("../../etc/passwd") returns False, because resolution
          happens BEFORE the prefix check rather than after it
        - never raises
    """
    # A pytest node id is "<path>::<class>::<test>" — only the path half is a file.
    path_part = raw_path.split( "::", 1 )[ 0 ]
    if not path_part: return False

    candidate = path_part if os.path.isabs( path_part ) else os.path.join( project_root, path_part )
    resolved  = os.path.realpath( candidate )

    for root in ALLOWED_TEST_ROOTS:
        root_resolved = os.path.realpath( os.path.join( project_root, root ) )
        # The trailing separator matters: without it "/a/src/testsEVIL" would
        # pass a prefix check against "/a/src/tests".
        if resolved == root_resolved or resolved.startswith( root_resolved + os.sep ):
            return True
    return False


def validate_pytest_args( tokens, project_root ):
    """
    Validate already-parsed pytest argument tokens against the allowlist.

    Requires:
        - tokens is a list of strings (typically the output of shlex.split)
        - project_root is an absolute path to the repository root

    Ensures:
        - returns None when every token is permitted
        - raises PytestArgsRejected naming the offending token and the reason
          when any token is not a recognised flag, a value bound to one, or a
          path confined to an allowed test root
        - the message echoes only the offending token, so a refusal cannot be
          used to reflect arbitrary content back to a caller

    Raises:
        - PytestArgsRejected on the first violation
    """
    if len( tokens ) > MAX_ARG_COUNT:
        raise PytestArgsRejected( f"too many pytest args: {len( tokens )} > {MAX_ARG_COUNT}" )

    expecting_value_for = None

    for token in tokens:
        if len( token ) > MAX_ARG_LENGTH:
            raise PytestArgsRejected( f"pytest arg exceeds {MAX_ARG_LENGTH} characters" )
        if "\x00" in token:
            raise PytestArgsRejected( "pytest arg contains a null byte" )

        # This token is the value of the flag seen on the previous iteration.
        if expecting_value_for is not None:
            flag                = expecting_value_for
            expecting_value_for = None
            if flag in PATH_VALUE_FLAGS and not _path_is_confined( token, project_root ):
                raise PytestArgsRejected(
                    f"path for {flag} must resolve inside {' or '.join( ALLOWED_TEST_ROOTS )}: {token!r}"
                )
            continue

        name = _flag_name( token )

        if name is None:
            # A bare token is a test path. THIS is the branch that matters:
            # pytest IMPORTS whatever it collects, so an unconfined path here
            # is arbitrary code execution.
            if not _path_is_confined( token, project_root ):
                raise PytestArgsRejected(
                    f"test path must resolve inside {' or '.join( ALLOWED_TEST_ROOTS )}: {token!r}"
                )
            continue

        if name in ALLOWED_BARE_FLAGS:
            if "=" in token:
                raise PytestArgsRejected( f"{name} takes no value" )
            continue

        if name in ALLOWED_VALUE_FLAGS:
            if "=" in token:
                value = token.split( "=", 1 )[ 1 ]
                if not value:
                    raise PytestArgsRejected( f"{name} given an empty value" )
                if name in PATH_VALUE_FLAGS and not _path_is_confined( value, project_root ):
                    raise PytestArgsRejected(
                        f"path for {name} must resolve inside {' or '.join( ALLOWED_TEST_ROOTS )}: {value!r}"
                    )
            else:
                expecting_value_for = name
            continue

        raise PytestArgsRejected( f"unrecognised pytest arg: {token!r}" )

    if expecting_value_for is not None:
        raise PytestArgsRejected( f"{expecting_value_for} is missing its value" )

    return None


def parse_and_validate( pytest_args_string, project_root ):
    """
    Parse a caller's raw pytest_args string and validate it.

    Requires:
        - pytest_args_string is a string or None
        - project_root is an absolute path to the repository root

    Ensures:
        - returns [] for None / empty / whitespace-only input
        - returns the shlex-parsed token list when every token is permitted
        - raises PytestArgsRejected on unbalanced quotes or any allowlist
          violation, so a bad request is refused at the door rather than at
          run time

    Raises:
        - PytestArgsRejected
    """
    if not pytest_args_string or not pytest_args_string.strip():
        return []

    try:
        tokens = shlex.split( pytest_args_string )
    except ValueError as error:
        raise PytestArgsRejected( f"could not parse pytest_args: {error}" )

    validate_pytest_args( tokens, project_root )
    return tokens
