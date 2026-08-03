#!/usr/bin/env python3
"""
vertex_publisher_config_guard.py — the clobber-trap guard (store cda7bf8b leg 5).

THE TRAP (live, not theoretical — cascade record 8093520f / 31f6d447):
`setPublisherModelConfig` has NO updateMask; its request schema has exactly one
field, `publisherModelConfig`. Every write is therefore a FULL-OBJECT SET, and a
partial payload SILENTLY WIPES whatever it omits (turning logging off wipes the
search gate; turning search on wipes logging).

THE GUARD: any config write must send the COMPLETE object. This module compares
a candidate payload against the LIVE config (fetched read-only by the executor)
and REFUSES the write when the candidate is missing any key the live config
carries. It also refuses (by default) when the candidate ADDS keys the live
config does not carry — because on this surface an added field can itself be a
disclosure opt-in (`dataSharingEnabledProvider` is the recorded example: setting
it "because it's free" IS a data-sharing decision). Additions must be
explicitly acknowledged with --allow-additions.

Usage (executor: Mr. Radio / Rick — this guard makes NO network calls):
    python3 src/scripts/vertex_publisher_config_guard.py \
        --live /tmp/live-config.json --candidate /tmp/new-config.json
    # exit 0 = write may proceed; exit 1 = REFUSED, reasons on stdout

Companion: src/scripts/vertex-config-double-write-proof.sh pipes its payload
through this guard before its live path (cda7bf8b leg 4).
"""

import argparse
import json
import sys


def find_missing_keys( live, candidate, path="" ):
    """
    Recursively find keys present in the live config but absent from the candidate.

    Requires:
        - live and candidate are the parsed JSON values being compared
        - path is the dotted prefix for reporting (empty at the root)

    Ensures:
        - returns a list of dotted key paths present in live but missing in candidate
        - recurses only into dicts; lists and scalars are treated as replaced-whole
        - returns [] when candidate carries every key live carries

    Raises:
        - nothing: non-dict nodes terminate recursion rather than erroring
    """
    if not isinstance( live, dict ) or not isinstance( candidate, dict ):
        return []

    missing = []
    for key, live_val in live.items():
        key_path = f"{path}.{key}" if path else key
        if key not in candidate:
            missing.append( key_path )
        else:
            missing.extend( find_missing_keys( live_val, candidate[ key ], key_path ) )
    return missing


def find_added_keys( live, candidate, path="" ):
    """
    Recursively find keys present in the candidate but absent from the live config.

    Requires:
        - live and candidate are the parsed JSON values being compared

    Ensures:
        - returns a list of dotted key paths the candidate introduces
        - an added key can be a silent opt-in (the 8093520f trap) — callers must
          surface these, never swallow them

    Raises:
        - nothing
    """
    if not isinstance( live, dict ) or not isinstance( candidate, dict ):
        return []

    added = []
    for key, cand_val in candidate.items():
        key_path = f"{path}.{key}" if path else key
        if key not in live:
            added.append( key_path )
        else:
            added.extend( find_added_keys( live[ key ], cand_val, key_path ) )
    return added


def check_payload( live, candidate, allow_additions=False ):
    """
    Decide whether a candidate full-object SET may proceed.

    Requires:
        - live is the parsed CURRENT config (read back from GCP by the executor)
        - candidate is the parsed payload about to be written

    Ensures:
        - returns ( ok, report ) where report carries 'missing', 'added', 'reasons'
        - ok is False if ANY live key is missing from the candidate (clobber)
        - ok is False if the candidate adds keys and allow_additions is False
        - ok is True otherwise; added keys still appear in the report for the record

    Raises:
        - nothing
    """
    missing = find_missing_keys( live, candidate )
    added   = find_added_keys( live, candidate )
    reasons = []

    if missing:
        reasons.append( f"CLOBBER: candidate omits {len( missing )} live key(s) — a full-object SET would wipe them: {missing}" )
    if added and not allow_additions:
        reasons.append( f"SILENT OPT-IN: candidate adds {len( added )} key(s) not in the live config: {added} — an added field can itself be a disclosure decision (8093520f); re-run with --allow-additions to acknowledge" )

    ok = not reasons
    return ok, { "missing": missing, "added": added, "reasons": reasons }


def main( argv=None ):
    """
    CLI entry point: load both JSON files, run the check, print the verdict.

    Requires:
        - --live and --candidate name readable JSON files

    Ensures:
        - prints ALLOW or REFUSED plus the report
        - returns process exit code 0 (allow) or 1 (refuse / unreadable input)

    Raises:
        - SystemExit via argparse on bad flags
    """
    parser = argparse.ArgumentParser( description="Clobber-trap guard for full-object PublisherModelConfig writes" )
    parser.add_argument( "--live",            required=True,        help="path to the CURRENT config JSON (read back from GCP)" )
    parser.add_argument( "--candidate",       required=True,        help="path to the payload JSON about to be written" )
    parser.add_argument( "--allow-additions", action="store_true",  help="acknowledge keys the candidate introduces (each may be an opt-in)" )
    args = parser.parse_args( argv )

    try:
        with open( args.live ) as f:
            live = json.load( f )
        with open( args.candidate ) as f:
            candidate = json.load( f )
    except ( OSError, json.JSONDecodeError ) as e:
        print( f"vertex-config-guard: REFUSED — cannot load inputs: {e}" )
        return 1

    ok, report = check_payload( live, candidate, allow_additions=args.allow_additions )

    if ok:
        print( "vertex-config-guard: ALLOW — candidate carries every live key" )
        if report[ "added" ]:
            print( f"  acknowledged additions: {report[ 'added' ]}" )
        return 0

    print( "vertex-config-guard: REFUSED" )
    for reason in report[ "reasons" ]:
        print( f"  - {reason}" )
    return 1


def quick_smoke_test():
    """
    Fast inline sanity check of the three verdict shapes.

    Ensures:
        - complete candidate → ok
        - partial candidate → refused with the omitted key named
        - additive candidate → refused without the flag, allowed with it
    """
    debug = True
    live      = { "loggingConfig": { "enabled": True }, "claudeFeatureConfig": { "advancedAiEnabled": False } }
    complete  = { "loggingConfig": { "enabled": False }, "claudeFeatureConfig": { "advancedAiEnabled": False } }
    partial   = { "loggingConfig": { "enabled": False } }
    additive  = { **complete, "dataSharingEnabledProvider": "anthropic" }

    ok, _      = check_payload( live, complete )
    if debug: print( f"complete -> {ok} (expect True)" )
    ok, report = check_payload( live, partial )
    if debug: print( f"partial  -> {ok} (expect False), missing={report[ 'missing' ]}" )
    ok, _      = check_payload( live, additive )
    if debug: print( f"additive -> {ok} (expect False without flag)" )
    ok, _      = check_payload( live, additive, allow_additions=True )
    if debug: print( f"additive+flag -> {ok} (expect True)" )


if __name__ == "__main__":
    sys.exit( main() )
