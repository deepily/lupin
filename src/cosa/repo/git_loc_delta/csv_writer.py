"""
CSV Writer — tidy-long output for the Daily LoC Delta tool.

Schema v2 (2026-05-21 — extended by Rachel 🕊️ for cross-repo aggregation
per cross-session DM design with María 🌸). Emits one row per
(date, file_type) bucket, now carrying explicit `repo` + `branch` columns:

    date,repo,branch,file_type,added,deleted,files_touched,commits
    2026-05-15,cosa,wip-v0.1.7,python,128,42,7,3
    2026-05-15,cosa,wip-v0.1.7,markdown,300,15,2,3
    ...

Schema rationale:
  - `repo` made explicit so cross-repo aggregation reduces to a single
    `pandas.concat([read_csv(p) for p in csvs])` + `groupby(date)` — no
    filename parsing or basename heuristics required.
  - `branch` made explicit for time-anchoring across branch lifetimes.
  - Long-form (one row per bucket) so downstream pivots stay stable
    across file-type cardinality changes.

A sidecar JSON file is written alongside the CSV via `write_sidecar()`
carrying immutable run metadata: csv_schema_version, repo, branch, rev_range,
since, until, generated_at. Aggregators read the sidecar (if present) or
fall back to filename-derived identity for legacy v1 CSVs.

Empty input produces a header-only CSV (documented behavior for empty
ranges). Reuses the COSA `to_csv(index=False)` pattern (Reuse Map R6).
"""

import json
import os
from datetime import datetime
from typing   import Dict, Optional, Tuple

import pandas as pd


# Schema v2: adds `repo` + `branch` columns between `date` and `file_type`
CSV_COLUMNS        = [ "date", "repo", "branch", "file_type", "added", "deleted", "files_touched", "commits" ]
CSV_SCHEMA_VERSION = 2


def write_csv(
    by_type: Dict[Tuple[str, str], Dict[str, int]],
    path:    str,
    repo:    str,
    branch:  Optional[str] = None,
    debug:   bool          = False,
) -> int:
    """
    Write the by-(date,file_type) view to a tidy-long CSV at `path`.

    Requires:
        - by_type is dict[(date, file_type)] → {added, deleted, files_touched, commits}
          (an empty dict is allowed and produces a header-only CSV)
        - path is a string path; parent directory will be created if missing
        - repo is a non-empty string (typically basename of repo root, or
          --repo-name override)
        - branch is the resolved branch name or None for non-branch modes
          (stored as empty string in the CSV when None)

    Ensures:
        - File written at `path` with the fixed CSV_COLUMNS header (schema v2)
        - Every row carries the same `repo` + `branch` values (immutable per file)
        - Rows sorted by (date ascending, added descending) for stable display
        - Returns the number of body rows written (0 for empty input)
    """
    branch_str = branch or ""

    rows = []
    for ( date, file_type ), counts in by_type.items():
        rows.append({
            "date":          date,
            "repo":          repo,
            "branch":        branch_str,
            "file_type":     file_type,
            "added":         counts["added"],
            "deleted":       counts["deleted"],
            "files_touched": counts["files_touched"],
            "commits":       counts["commits"],
        })

    rows.sort( key=lambda r: ( r["date"], -r["added"] ) )

    parent = os.path.dirname( path )
    if parent and not os.path.isdir( parent ):
        os.makedirs( parent, exist_ok=True )
        if debug: print( f"[csv_writer] Created directory: {parent}" )

    df = pd.DataFrame( rows, columns=CSV_COLUMNS )
    df.to_csv( path, index=False )

    if debug: print( f"[csv_writer] Wrote {len(rows)} rows to {path}" )
    return len( rows )


def write_sidecar(
    csv_path:  str,
    repo:      str,
    branch:    Optional[str],
    rev_range: Optional[str],
    since:     Optional[str],
    until:     Optional[str],
    debug:     bool          = False,
) -> str:
    """
    Write a sidecar JSON file carrying immutable run metadata for `csv_path`.

    The sidecar lives next to the CSV with `.meta.json` appended to the
    full filename (e.g. `cosa-wip-v0.1.7-loc-delta.csv` →
    `cosa-wip-v0.1.7-loc-delta.csv.meta.json`). Cross-repo aggregators read
    this to discover repo identity without parsing filenames.

    Requires:
        - csv_path points at a writable location; parent dir already exists
          (csv_writer.write_csv() creates it)
        - repo is a non-empty string
        - branch / rev_range / since / until may be None (omitted from JSON)

    Ensures:
        - File written at `{csv_path}.meta.json` with keys:
            csv_schema_version, repo, branch?, rev_range?, since?, until?, generated_at
        - generated_at is ISO-8601 UTC at write time
        - Returns the sidecar path written
        - None-valued metadata fields are still written (as JSON null) for
          shape stability across runs — consumers can rely on key presence
    """
    sidecar_path = f"{csv_path}.meta.json"

    payload = {
        "csv_schema_version": CSV_SCHEMA_VERSION,
        "repo":               repo,
        "branch":             branch,
        "rev_range":          rev_range,
        "since":              since,
        "until":              until,
        "generated_at":       datetime.utcnow().isoformat() + "Z",
    }

    with open( sidecar_path, "w" ) as f:
        json.dump( payload, f, indent=2 )
        f.write( "\n" )

    if debug: print( f"[csv_writer] Wrote sidecar {sidecar_path}" )
    return sidecar_path
