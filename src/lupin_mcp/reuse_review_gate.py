#!/usr/bin/env python3
"""
The reuse-review gating flag and the report-or-reject decision that reads it.

The reuse-reviewer skill (`.claude/skills/reuse-reviewer/`) collects findings from the linters
and from its own rulings. One key in the main configuration file, `reuse review gating`, sets
whether a finding blocks. Rick ruled that enforcement switches on once the checker pieces are built.

    - false: the skill reports every finding and rejects nothing.
    - true: the skill rejects the diff when a blocking finding remains.

Every finding has a kind. Only a `docstring_lint` finding is advisory and never blocks.
A finding that names a reuse-evidence kind blocks.
So does a finding with no kind, and one whose kind this module does not know.
When the gate is on, a doubtful finding fails closed.
A record in the linter's own JSON shape counts as `docstring_lint`.

The value is read fresh from the file on each call. The configuration manager is a
process-lifetime singleton and would keep a stale answer.

An absent, doubled, unreadable or garbled key means the gate could not check. The decision is then
`could-not-check` and the command exits 3, which is neither a pass nor a refusal. The skill and every
caller treat exit 3 as not passed, before and after the flip alike. A tagged line goes to stderr.
"""
import argparse
import json
import os
import sys

from lupin_mcp import fleet_cap_ini_io, fleet_size_cap

GATING_KEY   = "reuse review gating"
INI_OVERRIDE = "LUPIN_REUSE_REVIEW_INI"
LOG_TAG      = "[REUSE-REVIEW-GATE]"

REUSE_KINDS          = ( "no_receipt", "no_search_id", "no_outcome_line", "refused_outcome_line", "ignored_ruling" )
ADVISORY_KIND        = "docstring_lint"
LINTER_KEYS          = frozenset( { "path", "line", "rule", "message" } )       # the keys of a record the docstring and markdown linters print with --json
EXIT_REJECT          = 1
EXIT_COULD_NOT_CHECK = 3                                                           # 2 is taken by argparse and by the exit gate's malformed --run


def ini_path():
    """
    Name the configuration file the flag is read from.

    Ensures:
        - returns the env override when it is set, so tests never touch the live file
        - otherwise returns the main checkout's configuration file
    """
    override = os.environ.get( INI_OVERRIDE )
    if override: return override
    return fleet_size_cap.main_checkout_ini_path()


def _say( detail ):
    """Print one tagged line to stderr."""
    print( f"{LOG_TAG} {detail}", file=sys.stderr, flush=True )


def read_gating( path=None, quiet=False ):
    """
    Read the flag fresh from the configuration file.

    Requires:
        - path is a file path, or None for the default file
    Ensures:
        - returns True for a clean `true` and False for a clean `false`
        - returns None, meaning the gate could not check, for an absent, doubled, unreadable or garbled key
        - every answer that is not a clean boolean prints one tagged line, unless quiet
    """
    target = path if path is not None else ini_path()
    raw    = fleet_cap_ini_io.read_value_from_disk( target, GATING_KEY )     # a fresh disk read: ConfigurationManager is a process-lifetime singleton and would keep a stale value
    if raw is None:
        if not quiet: _say( f"could not read `{GATING_KEY}` from {target}; the gate could not check." )
        return None
    lowered = raw.strip().lower()
    if lowered in ( "true", "false" ): return lowered == "true"
    if not quiet: _say( f"`{GATING_KEY}` holds {raw!r}, which is not true or false; the gate could not check." )
    return None


def kind_of( finding ):
    """
    Name the kind of one finding.

    Requires:
        - finding is a dict or a string, as the skill writes them
    Ensures:
        - returns the finding's own `kind` when it is a dict holding a non-empty string kind
        - returns ADVISORY_KIND for a record in the linter's JSON shape: only the keys path, line, rule and message, with a non-empty rule id
        - returns None for anything else, including every string
    """
    if not isinstance( finding, dict ): return None
    kind = finding.get( "kind" )
    if isinstance( kind, str ) and kind: return kind
    if set( finding ) == LINTER_KEYS and isinstance( finding[ "rule" ], str ) and finding[ "rule" ]: return ADVISORY_KIND
    return None


def blocks( finding ):
    """
    Say whether one finding blocks a diff when the gate is on.

    Ensures:
        - returns True for a named reuse-evidence kind, those of REUSE_KINDS
        - returns False only for a `docstring_lint` finding
        - returns True for a kind this module does not know, and for a finding with no kind, which fail closed
    """
    kind = kind_of( finding )
    if kind in REUSE_KINDS: return True
    return kind != ADVISORY_KIND


def evaluate( findings, gating ):
    """
    Decide report-only, reject or could-not-check for a list of findings.

    Requires:
        - findings is a list of finding dicts or strings from the linters and the reuse rulings
        - gating is True, False, or None when read_gating could not check
    Ensures:
        - returns { mode, reject, count, blocking, findings }
        - gating None gives mode "could-not-check" and reject None: neither a pass nor a refusal
        - mode is "reject" when gating is true and "report-only" when it is false
        - blocking lists the findings that block, and reject is true only when gating is true and one remains
        - the findings are returned in every mode, so a report-only run loses nothing
    """
    blocking = [ f for f in findings if blocks( f ) ]
    if gating is None:
        return { "mode": "could-not-check", "reject": None, "count": len( findings ), "blocking": blocking, "findings": list( findings ) }
    return { "mode": "reject" if gating else "report-only", "reject": bool( gating and blocking ),
             "count": len( findings ), "blocking": blocking, "findings": list( findings ) }


def main( argv=None, out=None ):
    """
    Command line: print the decision for a JSON list of findings.

    Requires:
        - --findings names a JSON file holding a list
    Ensures:
        - prints the decision as JSON on `out`
        - returns 1 when the diff is rejected, 3 when the gate could not check, else 0
    """
    ap = argparse.ArgumentParser( description="Report or reject, by the `reuse review gating` flag." )
    ap.add_argument( "--findings", required=True )
    ap.add_argument( "--ini" )
    a   = ap.parse_args( argv )
    out = out if out is not None else sys.stdout
    with open( a.findings, encoding="utf-8" ) as handle: findings = json.load( handle )
    verdict = evaluate( findings, read_gating( a.ini ) )
    print( json.dumps( verdict, indent=2 ), file=out )
    if verdict[ "mode" ] == "could-not-check": return EXIT_COULD_NOT_CHECK
    return EXIT_REJECT if verdict[ "reject" ] else 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
