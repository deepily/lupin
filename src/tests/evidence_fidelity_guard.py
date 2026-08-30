"""
Evidence-fidelity guard (assigned by Cheech 2026-08-17; failure fixture f008951a,
right fixture 773ed129 / the maria raw dump).

THE FAILURE THIS PREVENTS. An evidence doc under src/rnd embeds a JSON block that
LOOKS like a raw capture but was built as `{ k: d.get(k) for k in [hardcoded keys] }`
— a PROJECTION over a fixed key list. `d.get()` on an ABSENT key returns None, which
renders as `null`, so a reader cannot tell "the key was present and null" from "the
key did not exist". On row e071e834 this manufactured a `manager_figure_implicit: null`
that the raw `.bridge.json` sibling did not contain (grep = 0), and it nearly sent the
a4d483e0 morning runner looking for a null that was never there. Presence and absence
are data; a projection that invents a key is worse than no capture because it reads as raw.

THE RULE (Cheech): copy the artifact, don't project it; if you project for readability,
LABEL it and ship the raw file beside it. When a .md and its raw sibling disagree, the
raw file wins.

SCOPE — GRANDFATHERED BY CONSTRUCTION, NOT BY A DATED ALLOWLIST (decided on the numbers,
2026-08-17: 63 src/rnd docs embed capture-shaped JSON, only 2 have a raw sibling). A guard
that failed on all 63 would be a red wall someone disables — worse than tonight. So this
guard checks ONLY the mechanically-verifiable claim: a .md that ships a raw `<md>.bridge.json`
sibling must not present a JSON key set that DISAGREES with that sibling unless the .md is
LABELLED a projection. A doc with no raw sibling makes no "this IS the raw bytes" claim there
is anything to check against, so it is out of scope — the label-and-ship-raw rule governs new
lone captures by practice, and this guard bites the moment a raw sibling exists.

Pure + import-clean so it is unit-testable in both directions without touching the tree.
"""

import json
import os
import re


# A .md is paired with its raw dump when `<md>.bridge.json` sits beside it.
RAW_SIBLING_SUFFIX = ".bridge.json"

# Markers that make a projection HONEST: the block is labelled as a projection and the
# reader is told not to read key presence off it. Any one present ⇒ labelled.
_LABEL_MARKERS = (
    "selective projection",
    "do not read key presence",
    "not a faithful dump",
)

# Fenced ```json blocks in a markdown doc.
_JSON_FENCE = re.compile( r"```json\s*\n(.*?)```", re.DOTALL )


def has_projection_label( md_text ):
    """True iff `md_text` labels its JSON as a projection (any _LABEL_MARKER, case-insensitive)."""
    low = md_text.lower()
    return any( marker in low for marker in _LABEL_MARKERS )


def _top_level_keys( json_text ):
    """The top-level key set of the FIRST parseable JSON object in `json_text`, or None."""
    try:
        obj = json.loads( json_text )
    except ( ValueError, TypeError ):
        return None
    if not isinstance( obj, dict ):
        return None
    return set( obj.keys() )


def embedded_json_key_sets( md_text ):
    """The top-level key set of each parseable ```json fenced block in `md_text`."""
    sets = []
    for block in _JSON_FENCE.findall( md_text ):
        keys = _top_level_keys( block )
        if keys is not None:
            sets.append( keys )
    return sets


def presence_disagreement( md_text, raw_json_text ):
    """
    The keys on which an UNLABELLED .md's embedded JSON disagrees with its raw sibling.

    Ensures:
        - Returns the set of top-level keys that appear in the .md's embedded JSON but
          NOT in the raw sibling, or vice-versa — the exact "invented / dropped a key"
          shape the f008951a failure had. Compares each embedded block against the raw
          key set and unions the disagreements.
        - Returns an empty set when the raw JSON is unparseable (nothing to compare
          against — fail-safe silent) or when every embedded block's key set matches.
    """
    raw_keys = _top_level_keys( raw_json_text )
    if raw_keys is None:
        return set()
    disagreements = set()
    for md_keys in embedded_json_key_sets( md_text ):
        disagreements |= ( md_keys ^ raw_keys )   # symmetric difference = presence mismatch
    return disagreements


def _walk_files( root ):
    """
    Every (dirpath, filename) under `root` — the ONE walk both the pair finder and the
    reach probe use, so a walk that silently sees nothing cannot report differently to them.
    """
    for dirpath, _dirnames, filenames in os.walk( root ):
        for name in filenames:
            yield dirpath, name


def find_paired_evidence( rnd_root ):
    """
    Every (md_path, raw_json_path) under `rnd_root` where `<md>.bridge.json` exists.

    Ensures:
        - Returns a sorted list of (md, raw) absolute-or-given-relative path pairs.
        - A raw dump with no .md partner (the honest standalone case, e.g. the maria
          bridge) yields NO pair — it makes no projection claim to verify.
    """
    pairs = []
    for dirpath, name in _walk_files( rnd_root ):
        if name.endswith( RAW_SIBLING_SUFFIX ):
            raw  = os.path.join( dirpath, name )
            md   = raw[ : -len( RAW_SIBLING_SUFFIX ) ]            # strip ".bridge.json"
            if os.path.exists( md ):
                pairs.append( ( md, raw ) )
    return sorted( pairs )


def scan_reach( rnd_root ):
    """
    How much the scan's walk actually SAW under `rnd_root`: { "files", "markdown", "raw_siblings" }.

    A clean verdict from check_evidence_tree() means "no dishonest pair" only if the walk
    reached real content. Pointed at a missing or wrong root it reaches nothing and reports
    clean — vacuously. This exposes the reach so a caller can tell the two apart.

    Requires:
        - `rnd_root` is a path; a missing one is not an error.

    Ensures:
        - Counts come from _walk_files, the SAME walk find_paired_evidence uses, so a
          broken walk reddens the reach probe too.
        - Returns all-zero counts for a missing or empty root rather than raising.
    """
    reach = { "files": 0, "markdown": 0, "raw_siblings": 0 }
    for _dirpath, name in _walk_files( rnd_root ):
        reach[ "files" ] += 1
        if name.endswith( ".md" ):                 reach[ "markdown" ]     += 1
        if name.endswith( RAW_SIBLING_SUFFIX ):    reach[ "raw_siblings" ] += 1
    return reach


def check_pair( md_text, raw_json_text ):
    """
    None iff this paired evidence doc is honest; else a reason string.

    A pair is honest when EITHER the .md is labelled a projection OR its embedded JSON
    agrees with the raw sibling on key presence. The failure — unlabelled AND
    disagreeing — is exactly f008951a.
    """
    if has_projection_label( md_text ):
        return None
    disagreement = presence_disagreement( md_text, raw_json_text )
    if disagreement:
        return ( "unlabelled projection: the .md's embedded JSON disagrees with its raw "
                 f".bridge.json sibling on key presence {sorted( disagreement )} and carries "
                 "no projection label — label it (\"SELECTIVE PROJECTION — do not read key "
                 "presence off it\") and let the raw file win, or fix the block to match." )
    return None


def check_evidence_tree( rnd_root ):
    """
    Scan `rnd_root` and return the list of fidelity problems (one string per bad pair).

    Ensures:
        - Empty list when every paired evidence doc is labelled-or-agreeing.
        - Otherwise one reason per offending pair, naming the .md path — so a projection
          can never again pass as raw beside a disagreeing sibling.
    """
    problems = []
    for md, raw in find_paired_evidence( rnd_root ):
        with open( md, encoding="utf-8" ) as handle:
            md_text = handle.read()
        with open( raw, encoding="utf-8" ) as handle:
            raw_text = handle.read()
        reason = check_pair( md_text, raw_text )
        if reason is not None:
            problems.append( f"{md}: {reason}" )
    return problems
