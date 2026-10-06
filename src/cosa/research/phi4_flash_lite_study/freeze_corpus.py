"""
Freeze the DM replay set for the Phi-4 vs Flash-Lite study.

Why freeze at all: `dm_traffic.jsonl` is an append-only log that the live fleet is
still writing to. Two arms replayed against a moving file are not paired. Arm 2 sees
rows arm 1 never saw, and every per-body comparison silently compares two different
datasets. The snapshot is what makes "same replayed DM bodies" true.

Where the corpus is: never `/var/lupin/dm-corpus`, which is the container mount point
and does not exist on the host where this harness runs. A guard pointed at a path that
never matches passes by default. This module resolves the live path by importing
`_resolve_dm_corpus_dir` from `src/cosa/rest/routers/dm.py` rather than copying its
two-step resolution ($LUPIN_DM_CORPUS_DIR, then fleet_data_root()/dm-corpus). A copy
drifts, and a drifted copy stops guarding.

The guard: `assert_snapshot_is_not_live()` raises when the snapshot is the same file
as the live corpus. It checks two ways, because either alone has a hole:

  1. `os.path.realpath` on both beats a symlink, a `..` segment and a trailing slash.
  2. `(st_dev, st_ino)` on both, when both exist, beats a hard link and a bind mount.
     `/var/lupin/dm-corpus` and the host's `projects-data/lupin/dm-corpus` are the
     same bytes under two paths. Realpath compares equal to neither, and only the
     inode identity catches it.

Run:
    python -m cosa.research.phi4_flash_lite_study.freeze_corpus --out-dir <dir>
        [--all-rows] [--sample N --seed S] [--trigger-claims 4] [--verify]
"""

import os
import sys
import json
import random
import hashlib
import argparse
import datetime
import subprocess

import cosa.utils.util as cu


CORPUS_FILENAME  = "dm_traffic.jsonl"
SNAPSHOT_FILENAME = "dm_replay_frozen.jsonl"
MANIFEST_FILENAME = "manifest.json"
MANIFEST_VERSION = 2

# A freeze that yields nothing is not a freeze, it is a silent study-killer: the
# claim counter fails open to 0 (`_count_claims` catches bare Exception), which
# marks EVERY row ineligible, and the manifest then records an empty replay set as
# a clean run. One row is the arithmetic floor; the study's own discordant floor is
# Rick's number and is checked separately, before arm 1.
MINIMUM_FROZEN_ROWS = 1


class LivePathRefused( RuntimeError ):
    """Raised when a caller aims the harness at the live, still-growing corpus."""


class EmptyReplaySet( RuntimeError ):
    """Raised when a freeze produced no rows — an empty study input, recorded as clean."""


class SourceChangedDuringRead( RuntimeError ):
    """Raised when the live corpus grew between the checksum and the read."""


def resolve_live_corpus_path():
    """
    The path the running fleet appends DM rows to.

    Delegates to the production resolver so the harness and the writer cannot disagree.
    Imported lazily, so the pure helpers (checksums, guard comparison, sampling) stay
    testable without the FastAPI router.

    Requires:
        - nothing

    Ensures:
        - returns an absolute path ending in dm_traffic.jsonl
        - the value equals what `src/cosa/rest/routers/dm.py` itself writes to
        - never returns the container mount `/var/lupin/...` unless the host's own
          $LUPIN_DM_CORPUS_DIR points there

    Raises:
        - ImportError if the production router cannot be imported
    """
    from cosa.rest.routers.dm import _resolve_dm_corpus_dir
    return os.path.join( _resolve_dm_corpus_dir(), CORPUS_FILENAME )


def assert_snapshot_is_not_live( snapshot_path, live_path=None ):
    """
    Refuse to treat the live append-only corpus as a frozen replay set.

    Requires:
        - snapshot_path is a string path

    Ensures:
        - returns the realpath of snapshot_path when it is not the live corpus
        - compares realpaths, so a symlink, a "..", or a trailing slash cannot
          smuggle the live file past the check
        - also compares ( st_dev, st_ino ) when both files exist, so a hard link or
          a bind mount — two real paths over one set of bytes — cannot either

    Raises:
        - LivePathRefused when snapshot_path is the live corpus file by either test
    """
    live     = live_path if live_path is not None else resolve_live_corpus_path()
    snap_rp  = os.path.realpath( snapshot_path )
    live_rp  = os.path.realpath( live )

    if snap_rp == live_rp:
        raise LivePathRefused(
            f"refusing to use the LIVE corpus as a replay set: {snap_rp}. "
            f"The fleet is still appending to this file, so the two arms would not "
            f"be paired. Freeze it first with freeze_corpus.py and pass the snapshot."
        )

    # Inode identity. Only meaningful when both files exist; a snapshot that has not
    # been written yet cannot be the live file, so a missing stat is not a failure.
    snap_id = _file_identity( snap_rp )
    live_id = _file_identity( live_rp )
    if snap_id is not None and snap_id == live_id:
        raise LivePathRefused(
            f"refusing to use the LIVE corpus as a replay set: {snap_rp} and {live_rp} "
            f"are the SAME FILE (device {snap_id[ 0 ]}, inode {snap_id[ 1 ]}) — a hard link "
            f"or a bind mount, which comparing paths alone would have let through."
        )
    return snap_rp


def assert_dir_is_not_live_corpus_dir( candidate_dir, live_path=None ):
    """
    Refuse to read a replay set out of, or write one into, the live corpus's dir.

    The file-level guard compares file names, so a caller aimed at the live directory
    passes it and gets a confusing FileNotFoundError, not a refusal. Nothing in the live
    directory is a frozen replay set, so the directory itself is refused.

    Requires:
        - candidate_dir is a string path

    Ensures:
        - returns the realpath of candidate_dir when it is not the live corpus's dir
        - catches the directory by realpath and by ( st_dev, st_ino ), for the same
          bind-mount reason as the file-level guard

    Raises:
        - LivePathRefused when candidate_dir is the live corpus's own directory
    """
    live      = live_path if live_path is not None else resolve_live_corpus_path()
    live_dir  = os.path.realpath( os.path.dirname( live ) )
    cand_dir  = os.path.realpath( candidate_dir )

    cand_id = _file_identity( cand_dir )
    if cand_dir == live_dir or ( cand_id is not None and cand_id == _file_identity( live_dir ) ):
        raise LivePathRefused(
            f"refusing to use the LIVE corpus directory as a replay set: {cand_dir}. "
            f"The fleet appends to this directory; nothing in it is frozen. Freeze into a "
            f"separate directory and point --snapshot-dir at that."
        )
    return cand_dir


def _file_identity( path ):
    """
    ( st_dev, st_ino ) for a path, or None when it cannot be stat'ed.

    Requires:
        - path is a string

    Ensures:
        - returns a ( device, inode ) tuple for an existing file
        - returns None for a path that does not exist, rather than raising — the
          snapshot legitimately does not exist yet when the guard runs

    Raises:
        - nothing
    """
    try:
        info = os.stat( path )
        return ( info.st_dev, info.st_ino )
    except OSError:
        return None


def sha256_of_file( path ):
    """
    Checksum a file in chunks.

    Requires:
        - path names a readable file

    Ensures:
        - returns a 64-character lowercase hex digest
        - reads in bounded chunks, so a multi-hundred-MB corpus does not have to
          fit in memory

    Raises:
        - OSError if the file cannot be read
    """
    digest = hashlib.sha256()
    with open( path, "rb" ) as handle:
        for chunk in iter( lambda: handle.read( 1024 * 1024 ), b"" ):
            digest.update( chunk )
    return digest.hexdigest()


def sha256_of_rows( rows ):
    """
    Checksum a list of row dicts by the exact bytes they will be written as.

    Requires:
        - rows is a list of JSON-serializable dicts

    Ensures:
        - returns a 64-character lowercase hex digest over the newline-delimited,
          sort_keys=True serialization — the same bytes `write_snapshot` emits,
          so the manifest's checksum can be re-derived from the file on disk

    Raises:
        - TypeError if a row is not JSON-serializable
    """
    digest = hashlib.sha256()
    for row in rows:
        digest.update( (json.dumps( row, sort_keys=True, ensure_ascii=False ) + "\n").encode( "utf-8" ) )
    return digest.hexdigest()


def read_corpus_rows( path ):
    """
    Read a DM corpus jsonl into a list of dicts.

    Requires:
        - path names a readable newline-delimited JSON file

    Ensures:
        - returns ( rows, skipped ) where skipped counts unparseable non-blank lines
        - blank lines are ignored and are not counted as skipped
        - a truncated final line (the writer appending mid-read) is counted in
          skipped rather than aborting the freeze

    Raises:
        - OSError if the file cannot be read
    """
    rows    = []
    skipped = 0
    with open( path, "r", encoding="utf-8" ) as handle:
        for line in handle:
            line = line.strip()
            if not line: continue
            try:
                rows.append( json.loads( line ) )
            except ValueError:
                skipped += 1
    return rows, skipped


def count_claims( body_text ):
    """
    Count the claim-bearing sentences in a body, via the router's own counter.

    Imports the router's `_count_claims`, which the tutor compares to its trigger,
    because a copy drifts. It fails open to 0 (no claims), which would freeze an empty
    replay set here, so `freeze()` refuses a zero-row result.

    Requires:
        - body_text is a string

    Ensures:
        - returns a non-negative int, identical to what the tutor's trigger reads

    Raises:
        - ImportError if the production router cannot be imported
    """
    from cosa.rest.routers.dm import _count_claims
    return _count_claims( body_text )


def select_eligible( rows, trigger_claims ):
    """
    Keep the rows whose body would actually put the tutor over its trigger.

    Requires:
        - rows is a list of dicts
        - trigger_claims is an int

    Ensures:
        - returns rows whose "body" is non-blank and whose claim count is
          strictly greater than trigger_claims — the same `>` the router uses at
          the `claims_in <= trigger` early return
        - preserves input order, so the frozen set is deterministic

    Raises:
        - nothing
    """
    keep = []
    for row in rows:
        body = row.get( "body" ) or ""
        if not body.strip(): continue
        if count_claims( body ) > trigger_claims: keep.append( row )
    return keep


def sample_rows( rows, sample_size, seed ):
    """
    Take a deterministic sample so a cost-bounded run is still reproducible.

    Requires:
        - rows is a list
        - sample_size is None or a positive int
        - seed is an int

    Ensures:
        - returns rows unchanged when sample_size is None or >= len( rows )
        - otherwise returns a sample of exactly sample_size rows, in the original
          corpus order, chosen by a Random seeded with `seed` — same seed, same
          rows, on any machine
        - never mutates the input list

    Raises:
        - nothing
    """
    if sample_size is None or sample_size >= len( rows ): return list( rows )
    picked = random.Random( seed ).sample( range( len( rows ) ), sample_size )
    picked.sort()
    return [ rows[ i ] for i in picked ]


def write_snapshot( rows, out_path ):
    """
    Write the frozen replay set as newline-delimited JSON.

    Requires:
        - rows is a list of JSON-serializable dicts
        - out_path's parent directory exists or can be created

    Ensures:
        - writes one sort_keys=True JSON object per line, UTF-8, trailing newline
        - the file's sha256 equals sha256_of_rows( rows )

    Raises:
        - OSError if the file cannot be written
    """
    parent = os.path.dirname( os.path.abspath( out_path ) )
    if parent: os.makedirs( parent, exist_ok=True )
    with open( out_path, "w", encoding="utf-8" ) as handle:
        for row in rows:
            handle.write( json.dumps( row, sort_keys=True, ensure_ascii=False ) + "\n" )


def current_git_sha():
    """
    The commit the freeze ran at, for provenance.

    Requires:
        - nothing

    Ensures:
        - returns a short sha string, or None when git cannot be consulted — a
          missing sha must never abort a freeze

    Raises:
        - nothing
    """
    try:
        out = subprocess.run(
            [ "git", "rev-parse", "--short", "HEAD" ], cwd=cu.get_project_root(),
            capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def build_manifest( source_path, source_sha, source_rows, source_skipped,
                    snapshot_path, snapshot_rows, trigger_claims,
                    eligible_only, sample_size, seed, frozen_at ):
    """
    Assemble the record that makes this snapshot re-derivable.

    Requires:
        - snapshot_rows is the list actually written to snapshot_path

    Ensures:
        - returns a dict carrying source path + freeze timestamp + row counts +
          checksums for both the source file and the written snapshot
        - records the selection parameters (trigger, eligible_only, sample, seed)
          so the same replay set can be rebuilt from the same source

    Raises:
        - nothing
    """
    return {
        "manifest_version"     : MANIFEST_VERSION,
        "study"                : "phi4-vs-flash-lite",
        "frozen_at_utc"        : frozen_at,
        "git_sha"              : current_git_sha(),
        "source_path"          : source_path,
        "source_sha256"        : source_sha,
        "source_row_count"     : source_rows,
        "source_skipped_lines" : source_skipped,
        "snapshot_path"        : os.path.abspath( snapshot_path ),
        "snapshot_sha256"      : sha256_of_rows( snapshot_rows ),
        "snapshot_row_count"   : len( snapshot_rows ),
        "selection"            : {
            "trigger_claims" : trigger_claims,
            "eligible_only"  : bool( eligible_only ),
            "sample_size"    : sample_size,
            "seed"           : seed,
        },
    }


def freeze( out_dir, trigger_claims=4, eligible_only=True, sample_size=None,
            seed=20260817, live_path=None, now=None, minimum_rows=MINIMUM_FROZEN_ROWS ):
    """
    Snapshot the live corpus into a frozen, checksummed replay set.

    Requires:
        - out_dir is a writable directory path that is not the live corpus's own
          directory

    Ensures:
        - writes <out_dir>/dm_replay_frozen.jsonl and <out_dir>/manifest.json
        - the manifest records source path, freeze timestamp, row counts and
          checksums for both the source and the snapshot
        - the source is checksummed before and after the read, so a digest can
          never describe bytes other than the ones that were read — the corpus
          grows ~5 rows/min while this runs
        - refuses to record an empty (or under-minimum) replay set as a clean freeze
        - returns the manifest dict

    Raises:
        - LivePathRefused if the snapshot would be written into or over the live corpus
        - SourceChangedDuringRead if the corpus grew between the two checksums
        - EmptyReplaySet if fewer than minimum_rows rows survived selection
        - OSError on unreadable source or unwritable destination
    """
    source        = live_path if live_path is not None else resolve_live_corpus_path()
    snapshot_path = os.path.join( out_dir, SNAPSHOT_FILENAME )

    # Both guards run BEFORE anything is read or written: aiming the freeze at the
    # live file would otherwise overwrite the fleet's own log, and aiming it at the
    # live DIRECTORY would drop a snapshot into the append-only tree.
    assert_dir_is_not_live_corpus_dir( out_dir, live_path=source )
    assert_snapshot_is_not_live( snapshot_path, live_path=source )

    # Checksum, read, checksum again. The corpus is append-only and live; a digest
    # taken before the read describes a file that may have grown by the time the
    # read finishes, and the manifest would then pin bytes nobody replayed.
    source_sha        = sha256_of_file( source )
    all_rows, skipped = read_corpus_rows( source )
    source_sha_after  = sha256_of_file( source )
    if source_sha != source_sha_after:
        raise SourceChangedDuringRead(
            f"{source} changed while it was being read ({source_sha[ :12 ]} -> "
            f"{source_sha_after[ :12 ]}). The manifest would pin a digest that does not "
            f"describe the rows that were frozen. Re-run the freeze."
        )

    rows = select_eligible( all_rows, trigger_claims ) if eligible_only else list( all_rows )
    rows = sample_rows( rows, sample_size, seed )

    if len( rows ) < minimum_rows:
        raise EmptyReplaySet(
            f"freeze produced {len( rows )} row(s) from {len( all_rows )} source rows, under the "
            f"minimum of {minimum_rows}. An empty replay set records as a clean freeze and then "
            f"measures nothing. Check the claim counter — it fails open to 0, which marks every "
            f"row ineligible."
        )

    write_snapshot( rows, snapshot_path )

    frozen_at = now if now is not None else datetime.datetime.now( datetime.timezone.utc ).isoformat()
    manifest  = build_manifest(
        source_path=source, source_sha=source_sha, source_rows=len( all_rows ),
        source_skipped=skipped, snapshot_path=snapshot_path, snapshot_rows=rows,
        trigger_claims=trigger_claims, eligible_only=eligible_only,
        sample_size=sample_size, seed=seed, frozen_at=frozen_at
    )
    manifest[ "minimum_rows" ] = minimum_rows
    with open( os.path.join( out_dir, MANIFEST_FILENAME ), "w", encoding="utf-8" ) as handle:
        json.dump( manifest, handle, indent=2, sort_keys=True )
        handle.write( "\n" )
    return manifest


def verify_snapshot( snapshot_path, manifest_path ):
    """
    Re-derive the snapshot's checksum and compare it to the manifest.

    Requires:
        - both paths name readable files

    Ensures:
        - returns ( ok, detail ) where ok is True only when the file's sha256 and
          row count both match the manifest and the snapshot is non-empty
        - a zero-row snapshot fails, even when it matches its manifest perfectly —
          an empty replay set is internally consistent and still measures nothing
        - detail names which field disagreed, so a mismatch is diagnosable

    Raises:
        - OSError if either file cannot be read
    """
    with open( manifest_path, "r", encoding="utf-8" ) as handle:
        manifest = json.load( handle )

    rows, skipped = read_corpus_rows( snapshot_path )
    actual_sha    = sha256_of_rows( rows )
    minimum       = manifest.get( "minimum_rows", MINIMUM_FROZEN_ROWS )

    if skipped:
        return False, f"{skipped} unparseable line(s) in the snapshot"
    if len( rows ) < minimum:
        return False, (
            f"snapshot holds {len( rows )} row(s), under the minimum of {minimum} — an empty "
            f"replay set is self-consistent and measures nothing"
        )
    if len( rows ) != manifest[ "snapshot_row_count" ]:
        return False, f"row count {len( rows )} != manifest {manifest[ 'snapshot_row_count' ]}"
    if actual_sha != manifest[ "snapshot_sha256" ]:
        return False, f"sha256 {actual_sha} != manifest {manifest[ 'snapshot_sha256' ]}"
    return True, "snapshot matches manifest"


def main( argv=None, printer=print ):
    """
    Command-line entry point.

    It is tested rather than excluded from coverage: `argv` and `printer` are
    injectable, so the exit codes and output can be asserted.

    Requires:
        - argv is None (read sys.argv) or a list of arguments

    Ensures:
        - returns 0 on a successful freeze or a passing verify
        - returns 1 on a failing verify
        - prints the manifest (freeze) or the verdict line (verify)

    Raises:
        - whatever freeze() raises — a refused live path or an empty replay set is
          a hard stop, not an exit code to be mistaken for a clean run
    """
    parser = argparse.ArgumentParser( description="Freeze the DM replay set for the Phi-4 vs Flash-Lite study" )
    parser.add_argument( "--out-dir",        required=True, help="directory to write the snapshot + manifest into" )
    parser.add_argument( "--trigger-claims", type=int, default=4, help="tutor trigger; rows over this are eligible" )
    parser.add_argument( "--all-rows",       action="store_true", help="freeze every row, not just tutor-eligible ones" )
    parser.add_argument( "--sample",         type=int, default=None, help="deterministic sample size" )
    parser.add_argument( "--seed",           type=int, default=20260817, help="sample seed, recorded in the manifest" )
    parser.add_argument( "--verify",         action="store_true", help="verify an existing snapshot instead of freezing" )
    parser.add_argument( "--minimum-rows",   type=int, default=MINIMUM_FROZEN_ROWS,
                         help="refuse a freeze that yields fewer rows than this" )
    args = parser.parse_args( argv )

    if args.verify:
        ok, detail = verify_snapshot(
            os.path.join( args.out_dir, SNAPSHOT_FILENAME ),
            os.path.join( args.out_dir, MANIFEST_FILENAME )
        )
        printer( f"{'OK  ' if ok else 'FAIL'}  {detail}" )
        return 0 if ok else 1

    manifest = freeze(
        out_dir=args.out_dir, trigger_claims=args.trigger_claims,
        eligible_only=not args.all_rows, sample_size=args.sample, seed=args.seed,
        minimum_rows=args.minimum_rows
    )
    printer( json.dumps( manifest, indent=2, sort_keys=True ) )
    return 0


if __name__ == "__main__":                                                 # pragma: no cover
    sys.exit( main() )
