"""
Corpus fingerprint — does this training artifact match the corpus on disk?

The training script used to ask whether the dataset EXISTS. It never asked
whether it is CURRENT, so a corpus edit followed by a training run trained on
the previous corpus and looked completely normal doing it (row 11390b57).

The fix, as ruled: hash the corpus, stamp the hash into the artifact at
generation, and REFUSE on mismatch. Refuse rather than silently regenerate —
a run that quietly rebuilds can quietly rebuild from the wrong side.

Two decisions worth knowing before reading the code:

1. We hash the LOADER-VISIBLE projection, not raw bytes. Every corpus read in
   xml_coordinator.py passes clean=True, skip_empty=True, skip_comments=True,
   so a comment edit or a line-ending change cannot reach training. Hashing raw
   bytes would refuse such a run, and a false refusal on a P1 path is how a
   guard gets switched off. We reuse du.get_file_as_list rather than
   reimplementing the skip rules — a second copy of "what counts as a comment"
   drifts, and the hash then quietly stops matching the training input.

2. We hash WHOLE files even where the caller later shuffles and slices. Two
   call sites (xml_coordinator.py:360, 437) pass randomize=True and slice
   [0:100], so a change past that cut cannot affect the artifact yet still
   flips the hash. That is a false refusal, not a false pass, and it is
   deliberate: narrowing the hash to the post-truncation set would couple it to
   the shuffle seed and the slice width, which is far easier to get quietly
   wrong.
"""
import hashlib
import json
import os

import cosa.utils.util as du

# Where the artifact and its stamp live, relative to the project root.
ARTIFACT_DIR_REL     = "/src/ephemera/prompts/data"
FINGERPRINT_FILENAME = "voice-commands-xml.fingerprint.json"
ARTIFACT_FILENAMES   = (
    "voice-commands-xml-train.jsonl",
    "voice-commands-xml-test.jsonl",
    "voice-commands-xml-validate.jsonl",
)
FINGERPRINT_VERSION  = 1

# The manifests that feed build_all_training_prompts. Plain form: command -> path.
PLAIN_MANIFESTS = (
    "/src/conf/training/vox-cmd-compound-commands.json",
    "/src/conf/training/vox-cmd-simple-commands.json",
    "/src/conf/training/agent-router-compound-commands.json",
    "/src/conf/training/agent-router-simple-commands.json",
)
# Enriched form: command -> { "template_file": path, ... }.
ENRICHED_MANIFESTS = (
    "/src/conf/training/agent-router-agentic-commands.json",
)
# Deliberately NOT covered: the function-mapping corpus read at
# xml_coordinator.py:437. It passes clean=True like the others, but it is not on
# the build_all_training_prompts path, so hashing it would refuse runs over a
# file that cannot reach the artifact.

# Verify outcomes.
VERDICT_MATCH           = "match"
VERDICT_MISMATCH        = "mismatch"
VERDICT_ARTIFACT_ABSENT = "artifact_absent"
VERDICT_STAMP_ABSENT    = "stamp_absent"

# CLI exit codes. 2 means "no artifact yet" so the caller can generate one.
EXIT_OK              = 0
EXIT_REFUSE          = 1
EXIT_ARTIFACT_ABSENT = 2


def _loader_visible_lines( abs_path: str ) -> list[str]:
    """
    Read one corpus file exactly the way the training loader reads it.

    Requires:
        - abs_path is a readable text file

    Ensures:
        - returns the stripped, non-empty, non-comment lines, in file order
        - applies no shuffling, so the result is deterministic
    """
    return du.get_file_as_list( abs_path, clean=True, skip_empty=True, skip_comments=True )


def collect_corpus_entries( path_prefix: str ) -> list[dict]:
    """
    List every corpus file that feeds the training artifact, in manifest order.

    Requires:
        - path_prefix is the project root
        - every manifest named in PLAIN_MANIFESTS / ENRICHED_MANIFESTS exists

    Ensures:
        - returns one dict per corpus file with keys manifest, command, path
        - order is manifest order, then declaration order within a manifest
    """
    entries = []

    for manifest_rel in PLAIN_MANIFESTS:
        with open( path_prefix + manifest_rel, "r" ) as f:
            commands = json.load( f )
        for command, corpus_rel in commands.items():
            entries.append( { "manifest": manifest_rel, "command": command, "path": corpus_rel } )

    for manifest_rel in ENRICHED_MANIFESTS:
        with open( path_prefix + manifest_rel, "r" ) as f:
            commands = json.load( f )
        for command, config in commands.items():
            entries.append( { "manifest": manifest_rel, "command": command, "path": config[ "template_file" ] } )

    return entries


def compute_fingerprint( path_prefix: str ) -> dict:
    """
    Hash the loader-visible content of every corpus file feeding the artifact.

    Requires:
        - path_prefix is the project root
        - every path named by a manifest exists and is readable

    Ensures:
        - returns { version, algo, projection, corpus_hash, files: [ ... ] }
        - files carries per-file command, path, line_count and sha256
        - corpus_hash covers command names, paths and lines in manifest order
    """
    aggregate = hashlib.sha256()
    files     = []

    for entry in collect_corpus_entries( path_prefix ):

        lines    = _loader_visible_lines( path_prefix + entry[ "path" ] )
        body     = "\n".join( lines )
        per_file = hashlib.sha256( body.encode( "utf-8" ) ).hexdigest()

        # Command name and path participate so a re-pointed or renamed command is a change.
        aggregate.update( entry[ "command" ].encode( "utf-8" ) )
        aggregate.update( b"\0" )
        aggregate.update( entry[ "path" ].encode( "utf-8" ) )
        aggregate.update( b"\0" )
        aggregate.update( per_file.encode( "utf-8" ) )
        aggregate.update( b"\0" )

        files.append( {
            "command"    : entry[ "command" ],
            "path"       : entry[ "path" ],
            "line_count" : len( lines ),
            "sha256"     : per_file
        } )

    return {
        "version"     : FINGERPRINT_VERSION,
        "algo"        : "sha256",
        "projection"  : "loader-visible (clean, skip_empty, skip_comments; no shuffle)",
        "corpus_hash" : aggregate.hexdigest(),
        "files"       : files
    }


def fingerprint_path( path_prefix: str ) -> str:
    """
    Absolute path of the sidecar stamp.

    Requires:
        - path_prefix is the project root

    Ensures:
        - returns the sidecar path beside the three JSONL artifacts
    """
    return path_prefix + ARTIFACT_DIR_REL + "/" + FINGERPRINT_FILENAME


def write_stamp( path_prefix: str, generated_at: str ) -> dict:
    """
    Stamp the current corpus fingerprint beside the artifact it was built from.

    Requires:
        - path_prefix is the project root
        - generated_at is an ISO-8601 timestamp string
        - the artifact directory exists and is writable

    Ensures:
        - writes the sidecar named by fingerprint_path()
        - returns the stamp that was written
    """
    stamp                   = compute_fingerprint( path_prefix )
    stamp[ "generated_at" ] = generated_at
    stamp[ "artifacts" ]    = list( ARTIFACT_FILENAMES )

    path = fingerprint_path( path_prefix )
    with open( path, "w" ) as f:
        json.dump( stamp, f, indent=4 )
    os.chmod( path, 0o666 )

    return stamp


def read_stamp( path_prefix: str ):
    """
    Read the sidecar stamp.

    Requires:
        - path_prefix is the project root

    Ensures:
        - returns the parsed stamp, or None when no sidecar exists
    """
    path = fingerprint_path( path_prefix )
    if not os.path.exists( path ): return None

    with open( path, "r" ) as f:
        return json.load( f )


def artifact_exists( path_prefix: str ) -> bool:
    """
    Report whether all three training artifacts are present.

    Requires:
        - path_prefix is the project root

    Ensures:
        - returns True only when every name in ARTIFACT_FILENAMES exists
    """
    for filename in ARTIFACT_FILENAMES:
        if not os.path.exists( path_prefix + ARTIFACT_DIR_REL + "/" + filename ): return False

    return True


def describe_mismatch( stamped: dict, current: dict ) -> str:
    """
    Say WHICH SIDE is stale, not merely that the two sides differ.

    A guard that reports "these differ" makes the reader supply a direction from
    whatever they already believe — which is the error this row exists to stop.
    So every line is labelled: ARTIFACT-SIDE is the corpus the dataset was built
    from, CORPUS-SIDE is the corpus on disk right now.

    Requires:
        - stamped and current are fingerprint dicts with corpus_hash and files

    Ensures:
        - returns a report naming both hashes, both sides of every differing
          file, and the direction of each line-count move
    """
    stamped_by_key = { ( f[ "command" ], f[ "path" ] ): f for f in stamped[ "files" ] }
    current_by_key = { ( f[ "command" ], f[ "path" ] ): f for f in current[ "files" ] }

    report = [
        "CORPUS FINGERPRINT MISMATCH — refusing to train on a dataset that was not built from this corpus.",
        "",
        f"  ARTIFACT-SIDE  the corpus this dataset was built from, stamped {stamped.get( 'generated_at', 'unknown time' )}",
        f"                 corpus_hash {stamped[ 'corpus_hash' ]}",
        "  CORPUS-SIDE    the corpus on disk right now",
        f"                 corpus_hash {current[ 'corpus_hash' ]}",
        ""
    ]

    for key in stamped_by_key:
        if key not in current_by_key:
            report.append( f"  ON THE ARTIFACT-SIDE ONLY — dropped from the manifest since generation: {key[ 0 ]} -> {key[ 1 ]}" )

    for key, current_file in current_by_key.items():

        if key not in stamped_by_key:
            report.append( f"  ON THE CORPUS-SIDE ONLY — added to the manifest since generation: {key[ 0 ]} -> {key[ 1 ]} ({current_file[ 'line_count' ]} lines)" )
            continue

        stamped_file = stamped_by_key[ key ]
        if stamped_file[ "sha256" ] == current_file[ "sha256" ]: continue

        delta = current_file[ "line_count" ] - stamped_file[ "line_count" ]
        if delta > 0:
            direction = f"the corpus on disk has {delta} MORE loader-visible lines than the corpus this dataset was built from"
        elif delta < 0:
            direction = f"the corpus on disk has {-delta} FEWER loader-visible lines than the corpus this dataset was built from"
        else:
            direction = "same line count on both sides, so lines were edited in place rather than added or removed"

        report.extend( [
            f"  {key[ 0 ]}",
            f"    {key[ 1 ]}",
            f"    ARTIFACT-SIDE  {stamped_file[ 'line_count' ]} loader-visible lines  sha256 {stamped_file[ 'sha256' ]}",
            f"    CORPUS-SIDE    {current_file[ 'line_count' ]} loader-visible lines  sha256 {current_file[ 'sha256' ]}",
            f"    DIRECTION      {direction}"
        ] )

    report.extend( [
        "",
        "  If the CORPUS-SIDE is the one you want, regenerate:  run-agentic-intent-training.sh generate",
        "  If the ARTIFACT-SIDE is the one you want, restore the corpus FIRST — regenerating now would rebuild from the corpus on disk."
    ] )

    return "\n".join( report )


def verify( path_prefix: str ) -> tuple[ str, str ]:
    """
    Decide whether a training run may proceed against the artifact on disk.

    Requires:
        - path_prefix is the project root

    Ensures:
        - returns ( verdict, report ) where verdict is one of VERDICT_MATCH,
          VERDICT_MISMATCH, VERDICT_ARTIFACT_ABSENT, VERDICT_STAMP_ABSENT
        - a VERDICT_MISMATCH report names which side is stale
        - proceeds only on VERDICT_MATCH
    """
    if not artifact_exists( path_prefix ):
        return VERDICT_ARTIFACT_ABSENT, "No training artifact on disk — nothing to check."

    stamped = read_stamp( path_prefix )
    if stamped is None:
        return VERDICT_STAMP_ABSENT, (
            "NO CORPUS FINGERPRINT BESIDE THIS ARTIFACT — refusing.\n"
            f"  expected {fingerprint_path( path_prefix )}\n"
            "  This dataset predates the freshness guard, so which corpus it was built from is unknown.\n"
            "  Two ways out, and they are NOT interchangeable — decide which side you trust FIRST:\n"
            "    the corpus on disk is the one you want  ->  run-agentic-intent-training.sh generate\n"
            "                                                (rebuilds from the corpus on disk, discarding this dataset)\n"
            "    this dataset is the one you want        ->  confirm the corpus on disk matches it, then\n"
            "                                                python -m cosa.training.corpus_fingerprint stamp\n"
            "  Do NOT reach for generate by reflex. If the corpus on disk is the stale side, regenerating\n"
            "  silently rebuilds from it and the good dataset is gone."
        )

    current = compute_fingerprint( path_prefix )
    if stamped[ "corpus_hash" ] == current[ "corpus_hash" ]:
        return VERDICT_MATCH, f"Corpus fingerprint matches: {current[ 'corpus_hash' ]} ({len( current[ 'files' ] )} corpus files)."

    return VERDICT_MISMATCH, describe_mismatch( stamped, current )


VERDICT_EXIT_CODES = {
    VERDICT_MATCH           : EXIT_OK,
    VERDICT_ARTIFACT_ABSENT : EXIT_ARTIFACT_ABSENT,
    VERDICT_MISMATCH        : EXIT_REFUSE,
    VERDICT_STAMP_ABSENT    : EXIT_REFUSE
}


def main( argv: list[str] ) -> int:
    """
    CLI entry point used by the two training arms.

    Requires:
        - argv names a sub-command, either "verify" or "stamp"
        - argv may carry --project-root PATH; otherwise the project root is used

    Ensures:
        - "verify" prints the report and returns 0 proceed / 1 refuse /
          2 no-artifact-yet
        - "stamp" writes the sidecar and returns 0
        - an unknown or missing sub-command prints usage and returns 1
    """
    path_prefix = du.get_project_root()
    if "--project-root" in argv:
        path_prefix = argv[ argv.index( "--project-root" ) + 1 ]

    if "verify" in argv:
        verdict, report = verify( path_prefix )
        print( report )
        return VERDICT_EXIT_CODES[ verdict ]

    if "stamp" in argv:
        from datetime import datetime, timezone
        stamp = write_stamp( path_prefix, datetime.now( timezone.utc ).isoformat() )
        print( f"Stamped corpus fingerprint {stamp[ 'corpus_hash' ]} over {len( stamp[ 'files' ] )} corpus files." )
        return EXIT_OK

    print( "Usage: python -m cosa.training.corpus_fingerprint {verify|stamp} [--project-root PATH]" )
    return EXIT_REFUSE


if __name__ == "__main__":                      # pragma: no cover - CLI shim, exercised via main()
    import sys                                  # pragma: no cover
    sys.exit( main( sys.argv[ 1: ] ) )          # pragma: no cover
