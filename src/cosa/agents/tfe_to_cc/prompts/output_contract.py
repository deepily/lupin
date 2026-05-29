"""
Output-contract parsers for the TFE-to-CC engine variant.

Claude Code emits diagnosis results as a fenced JSON block at end-of-run:

    ```tfe-diagnosis
    { "clusters": { "C1": {...} } }
    ```

The primary parser extracts that block. A defensive fallback parser does
best-effort markdown-regex recovery when the fenced block is missing or
malformed.

Design: src/rnd/v0.1.6/2026.04.10-test-fix-expediter/19-tfe-to-cc-design.md
"""

import json
import re
from typing import Optional


_DIAGNOSIS_FENCE = re.compile(
    r"```tfe-diagnosis\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)

_RESULT_FENCE = re.compile(
    r"```tfe-result\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)

_REQUIRED_CLUSTER_FIELDS = ( "root_cause", "error_category", "confidence" )
_REQUIRED_RESULT_FIELDS  = ( "verdict", )
_VALID_CATEGORIES = (
    "code_bug", "test_bug", "fixture_bug", "environment_bug",
)
_VALID_VERDICTS = ( "fixed", "failed", "unclear" )


def parse_diagnosis_block( text: Optional[ str ] ) -> Optional[ dict ]:
    """
    Extract + parse the `tfe-diagnosis` fenced JSON block from Claude Code output.

    Requires:
        - text is a string (or None)

    Ensures:
        - Returns the parsed dict on success (has 'clusters' key)
        - Returns None if:
            - text is empty/None
            - no fenced block found
            - JSON parse fails
            - top-level 'clusters' key missing
        - Never raises
    """
    if not text:
        return None

    m = _DIAGNOSIS_FENCE.search( text )
    if not m:
        return None

    body = m.group( "body" ).strip()
    try:
        parsed = json.loads( body )
    except ( json.JSONDecodeError, ValueError ):
        return None

    if not isinstance( parsed, dict ):
        return None
    if "clusters" not in parsed or not isinstance( parsed[ "clusters" ], dict ):
        return None

    return parsed


def validate_diagnosis_payload( payload: Optional[ dict ] ) -> tuple:
    """
    Validate a parsed diagnosis payload against the required schema.

    Requires:
        - payload is the output of parse_diagnosis_block (dict or None)

    Ensures:
        - Returns ( is_valid: bool, issues: list[str] )
        - is_valid is True iff:
            - payload is a dict with 'clusters' key
            - every cluster value is a dict with root_cause + error_category + confidence
            - error_category is one of the known values
            - confidence is a number in [0.0, 1.0]
        - issues is a list of human-readable problem descriptions (empty if valid)
    """
    issues: list = []

    if payload is None:
        return False, [ "payload is None (parse failed or block missing)" ]

    if not isinstance( payload, dict ):
        return False, [ f"payload is not a dict: {type( payload ).__name__}" ]

    clusters = payload.get( "clusters" )
    if not isinstance( clusters, dict ):
        return False, [ "payload missing 'clusters' key or it is not a dict" ]

    if not clusters:
        issues.append( "'clusters' is empty — no cluster diagnoses present" )

    for cid, cluster in clusters.items():
        if not isinstance( cluster, dict ):
            issues.append( f"cluster {cid!r}: value is not a dict" )
            continue

        for field in _REQUIRED_CLUSTER_FIELDS:
            if field not in cluster:
                issues.append( f"cluster {cid!r}: missing required field {field!r}" )

        cat = cluster.get( "error_category" )
        if cat is not None and cat not in _VALID_CATEGORIES:
            issues.append(
                f"cluster {cid!r}: unknown error_category {cat!r} "
                f"(expected one of {_VALID_CATEGORIES})"
            )

        conf = cluster.get( "confidence" )
        if conf is not None:
            try:
                conf_f = float( conf )
            except ( TypeError, ValueError ):
                issues.append( f"cluster {cid!r}: confidence is not a number: {conf!r}" )
            else:
                if not ( 0.0 <= conf_f <= 1.0 ):
                    issues.append(
                        f"cluster {cid!r}: confidence {conf_f} outside [0.0, 1.0]"
                    )

        root_cause = cluster.get( "root_cause" )
        if root_cause is not None and not isinstance( root_cause, str ):
            issues.append( f"cluster {cid!r}: root_cause is not a string" )
        elif isinstance( root_cause, str ) and len( root_cause.strip() ) < 10:
            issues.append(
                f"cluster {cid!r}: root_cause is suspiciously short "
                f"({len( root_cause.strip() )} chars) — likely uninformative"
            )

    return ( len( issues ) == 0 ), issues


def parse_result_block( text: Optional[ str ] ) -> Optional[ dict ]:
    """
    Extract + parse the `tfe-result` fenced JSON block from Claude Code Phase 3 output.

    Requires:
        - text is a string (or None)

    Ensures:
        - Returns the parsed dict on success (has 'clusters' key)
        - Returns None if no fence, no JSON, or schema-invalid at top level
        - Never raises
    """
    if not text:
        return None

    m = _RESULT_FENCE.search( text )
    if not m:
        return None

    body = m.group( "body" ).strip()
    try:
        parsed = json.loads( body )
    except ( json.JSONDecodeError, ValueError ):
        return None

    if not isinstance( parsed, dict ):
        return None
    if "clusters" not in parsed or not isinstance( parsed[ "clusters" ], dict ):
        return None

    return parsed


def validate_result_payload( payload: Optional[ dict ] ) -> tuple:
    """
    Validate a parsed `tfe-result` payload.

    Ensures:
        - Returns ( is_valid: bool, issues: list[str] )
        - is_valid iff:
            - payload is a dict with 'clusters' key
            - every cluster has 'verdict' in valid set
            - commit_sha present on verdict=='fixed' clusters (or explicitly null)
            - pytest_passed is bool when present
    """
    issues: list = []

    if payload is None:
        return False, [ "payload is None (parse failed or block missing)" ]
    if not isinstance( payload, dict ):
        return False, [ f"payload is not a dict: {type( payload ).__name__}" ]

    clusters = payload.get( "clusters" )
    if not isinstance( clusters, dict ):
        return False, [ "payload missing 'clusters' key or it is not a dict" ]

    if not clusters:
        issues.append( "'clusters' is empty — no cluster results present" )

    for cid, cluster in clusters.items():
        if not isinstance( cluster, dict ):
            issues.append( f"cluster {cid!r}: value is not a dict" )
            continue

        verdict = cluster.get( "verdict" )
        if verdict is None:
            issues.append( f"cluster {cid!r}: missing required field 'verdict'" )
        elif verdict not in _VALID_VERDICTS:
            issues.append(
                f"cluster {cid!r}: unknown verdict {verdict!r} "
                f"(expected one of {_VALID_VERDICTS})"
            )

        if verdict == "fixed":
            commit_sha = cluster.get( "commit_sha" )
            if not commit_sha or not isinstance( commit_sha, str ):
                issues.append(
                    f"cluster {cid!r}: verdict=fixed but commit_sha is missing or not a string"
                )

        pytest_passed = cluster.get( "pytest_passed" )
        if pytest_passed is not None and not isinstance( pytest_passed, bool ):
            issues.append( f"cluster {cid!r}: pytest_passed is not a bool: {pytest_passed!r}" )

    return ( len( issues ) == 0 ), issues


# ═════════════════════════════════════════════════════════════════════════
# Git log fallback — ground truth when the JSON block is missing/malformed
# ═════════════════════════════════════════════════════════════════════════

_TFE_COMMIT_PATTERN = re.compile(
    # SHA: git short/full shas are hex-only in reality, but we accept any
    # non-whitespace 7-40 char token so tests + mocks with non-hex stand-ins
    # parse correctly. Real git log output will only emit hex SHAs anyway.
    r"^(?P<sha>\S{7,40})\s+fix\(tfe\):\s+(?P<cid>C\d+)\b",
    re.IGNORECASE,
)


def parse_result_from_git_log( git_log_output: Optional[ str ], expected_cluster_ids: Optional[ list ] = None ) -> Optional[ dict ]:
    """
    Reconstruct a minimal result payload from `git log --oneline origin/main..HEAD`.

    This is the ground-truth fallback when Claude Code's `tfe-result` JSON block
    is missing/malformed. Every successful fix has a commit with a message matching
    `fix(tfe): C<id> ...`. We scan for those and build a payload.

    Requires:
        - git_log_output : `git log --oneline` output (newline-separated)
        - expected_cluster_ids : optional list of cluster_ids we dispatched; missing
          ones get verdict='unclear' (we can't distinguish "failed" from "not tried"
          without the JSON)

    Ensures:
        - Returns a dict with 'clusters' + 'summary' OR None if input is empty
        - Never raises
    """
    if not git_log_output or not git_log_output.strip():
        if expected_cluster_ids:
            # We know we were supposed to run these but git log is empty → all unclear/failed
            clusters = {
                cid: {
                    "verdict"       : "unclear",
                    "commit_sha"    : None,
                    "files"         : [],
                    "pytest_passed" : None,
                    "notes"         : "[git log fallback — no commits found; JSON block was also missing]",
                }
                for cid in expected_cluster_ids
            }
            return {
                "clusters" : clusters,
                "summary"  : f"0/{len( expected_cluster_ids )} fixed",
            }
        return None

    found: dict = {}
    for line in git_log_output.splitlines():
        m = _TFE_COMMIT_PATTERN.match( line.strip() )
        if not m:
            continue
        cid = m.group( "cid" ).upper()
        sha = m.group( "sha" )
        # First occurrence wins (git log is newest-first; most recent per cluster)
        if cid not in found:
            found[ cid ] = {
                "verdict"       : "fixed",
                "commit_sha"    : sha,
                "files"         : [],
                "pytest_passed" : None,
                "notes"         : "[git log fallback — commit found; JSON block was missing]",
            }

    # Add "unclear" entries for expected-but-not-found
    if expected_cluster_ids:
        for cid in expected_cluster_ids:
            if cid not in found:
                found[ cid ] = {
                    "verdict"       : "unclear",
                    "commit_sha"    : None,
                    "files"         : [],
                    "pytest_passed" : None,
                    "notes"         : "[git log fallback — no commit for this cluster; outcome unknown]",
                }

    if not found:
        return None

    fixed_count = sum( 1 for c in found.values() if c[ "verdict" ] == "fixed" )
    total = len( found )
    return {
        "clusters" : found,
        "summary"  : f"{fixed_count}/{total} fixed",
    }


def parse_diagnosis_fallback( text: Optional[ str ] ) -> Optional[ dict ]:
    """
    Best-effort markdown-regex recovery when the fenced JSON block is missing.

    This is intentionally conservative: we only return a payload when we can
    recover at least one cluster's root_cause + error_category. Otherwise we
    return None and the caller treats the run as "parse failed."

    Requires:
        - text is a string (or None)

    Ensures:
        - Returns dict matching the schema OR None
        - Never raises
    """
    if not text:
        return None

    # Look for patterns like "## Cluster C1 — ..." or "### C1:" or similar headers
    # followed by a "Root cause:" or "Diagnosis:" line.
    cluster_hdr = re.compile(
        r"(?:^|\n)#{1,6}\s*(?:Cluster\s+)?(?P<cid>C\d+)\b",
        re.IGNORECASE,
    )
    root_cause_line = re.compile(
        r"\*{0,2}(?:root\s*cause|diagnosis)\*{0,2}\s*:\s*(?P<rc>[^\n]+)",
        re.IGNORECASE,
    )
    category_line = re.compile(
        r"\*{0,2}(?:category|error[_\s]category)\*{0,2}\s*:\s*`?"
        r"(?P<cat>code_bug|test_bug|fixture_bug|environment_bug)`?",
        re.IGNORECASE,
    )

    # Split text into per-cluster chunks between successive cluster headers
    matches = list( cluster_hdr.finditer( text ) )
    if not matches:
        return None

    clusters: dict = {}
    for i, m in enumerate( matches ):
        cid = m.group( "cid" ).upper()
        start = m.end()
        end = matches[ i + 1 ].start() if i + 1 < len( matches ) else len( text )
        chunk = text[ start : end ]

        rc_m = root_cause_line.search( chunk )
        cat_m = category_line.search( chunk )

        if not rc_m:
            continue

        clusters[ cid ] = {
            "root_cause"          : rc_m.group( "rc" ).strip(),
            "error_category"      : ( cat_m.group( "cat" ).lower() if cat_m else "unknown" ),
            "confidence"          : 0.5,  # fallback default
            "affected_components" : [],
            "notes"               : "[fallback parser — fenced tfe-diagnosis block was missing or malformed]",
        }

    if not clusters:
        return None

    return { "clusters": clusters }
