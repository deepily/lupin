"""
Durable, tamper-EVIDENT attestation that a test tier actually ran (row 691d49db).

WHY THIS EXISTS
---------------
Three independent instruments could not answer "did tier X run, and did it lie?":

    host /tmp junit artifacts   -> wrong side of the container boundary
    container /tmp artifacts    -> 0 AT ANY DATE; a recreate wipes /tmp, and
                                   lupin-rest-test is the most-recreated
                                   container on the box
    job_history table           -> `test_suite` was never a job_type; newest row
                                   of ANY kind is 2026-05-12

Each of those would have rendered as a clean "0" in a summary line. That is the
defect: not a wrong number, but three instruments confidently answering a
question none of them can see.

TAMPER-EVIDENCE, NOT TAMPER-PROOFING — AND WHY THE WEAKER WORD IS THE HONEST ONE
-------------------------------------------------------------------------------
The original requirement was "write it somewhere the tests cannot write." That is
not achievable here, measured rather than argued:

    # job.py, the pytest Popen
    env={ **os.environ, "LUPIN_ROOT": …, "LUPIN_TEST_PORT": …, … }

The subprocess inherits the WHOLE parent environment. `_ENV_VAR_ALLOWED_PREFIXES`
( "TFE_", "BFE_", "LUPIN_TEST_" ) filters only the CALLER-SUPPLIED env_vars dict
submitted with the job — it does NOT scrub inheritance, though it reads as if it
does. So the tests hold every credential the orchestrator holds, run as the same
uid, in the same container, on the same filesystem. A Postgres table is reachable
with the app's own DSN; a bind mount with the app's own uid.

⇒ Building to "cannot write" would ship a receipt store whose guarantee is a
promise — which is this row's own defect one layer up. So: anyone may APPEND, and
nobody may REWRITE. Each record carries the sha256 of the previous record, so an
edit or a deletion breaks the chain at that point and `verify_chain` names the
first broken index.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
- It does not recover evidence from before it existed. Forward-only.
- It does not prevent tampering. It makes tampering VISIBLE.
- An empty store is NOT a pass. `verify_chain` returns status "no_records", never
  "valid" — unknown must not fold into a green, which is the exact trap this
  whole row is made of.
- ⚠️ Unit-green is NOT calibration. This module's tests prove the chain logic;
  they do NOT prove the writer is wired into a real tier run. That proof requires
  observing the store go 0→N on a live run and is owed separately — the
  instrument cannot be attested by the thing it exists to attest.
"""

import hashlib
import json
import os

import cosa.utils.util as cu

# ═══════════════════════════════════════════════════════════════════════════════
# Roots. Krishna's `fd0cd863` guard points at THESE — one definition, not a
# second hardcoded copy, so the guard and the writer cannot drift apart.
# ═══════════════════════════════════════════════════════════════════════════════

# `io/` is a BIND MOUNT on both containers (docker inspect:
# /mnt/DATA01/.../lupin/io -> /var/lupin/io rw=true), so it survives the recreate
# that wipes container /tmp. Everything below hangs off it.
TEST_SUITE_IO_SUBDIR   = "io/test-suite"
ATTESTATIONS_SUBDIR    = TEST_SUITE_IO_SUBDIR + "/attestations"
ARTIFACTS_SUBDIR       = TEST_SUITE_IO_SUBDIR + "/artifacts"
ATTESTATION_FILENAME   = "tier-runs.jsonl"

# The sha256 recorded as `prev_sha256` by the FIRST record. A literal rather than
# an empty string so a truncated file cannot be confused with a genesis record.
GENESIS_PREV = "0" * 64


def _refuse_implicit_root_under_pytest( caller ):
    """
    Raise when running under pytest with no explicit root.

    WHY THIS IS RUNTIME AND NOT A STATIC GUARD
    ------------------------------------------
    `fd0cd863` — a fixture writing the tier's REAL triage log path — would NOT
    have been caught by an AST scan for path literals, because those tests named
    no path at all: they called production code that computed it. Krishna found
    that hole in his own guard. A static scan matches a DESCRIPTION of the hazard;
    this matches the hazard, because it fires on the call itself no matter how the
    caller reached it.

    ⚠️ Scope, so the coupling is not a surprise: `PYTEST_CURRENT_TEST` is set for
    EVERY test in the repo, not just this suite's. Anything that transitively
    reaches these helpers under pytest must pass `project_root` explicitly.
    That is the point — accidental reach is exactly what leaked fixture strings
    into `/tmp/integration-latest.log` — but it means the blast radius is the
    whole test tree, and it is Krishna's wiring commit that absorbs it.
    """
    if os.environ.get( "PYTEST_CURRENT_TEST" ) is None: return
    raise RuntimeError(
        f"{caller}() was called under pytest without an explicit `project_root`. "
        f"Tests must not resolve the REAL artifact root — pass project_root=str( tmp_path ). "
        f"(Row fd0cd863: a fixture wrote the tier's real triage log path and a reader "
        f"triaged six lines of fixture text. This refusal is why that cannot recur.)"
    )


def artifact_root( project_root=None ):
    """
    Absolute path of the durable artifact directory.

    Requires:
        - project_root is None (resolve from the environment) or an absolute path
        - under pytest, project_root MUST be supplied — see
          _refuse_implicit_root_under_pytest

    Ensures:
        - returns an absolute path under the `io/` bind mount
        - creates nothing; callers decide when to make directories
        - RAISES rather than returning the real root to a test

    Raises:
        - RuntimeError when called under pytest with project_root=None
    """
    if project_root is None:
        _refuse_implicit_root_under_pytest( "artifact_root" )
        project_root = cu.get_project_root()
    return os.path.join( project_root, ARTIFACTS_SUBDIR )


def attestation_path( project_root=None ):
    """
    Absolute path of the append-only attestation ledger.

    Requires:
        - project_root is None (resolve from the environment) or an absolute path
        - under pytest, project_root MUST be supplied

    Ensures:
        - returns an absolute path under the `io/` bind mount
        - creates nothing
        - RAISES rather than returning the real ledger path to a test

    Raises:
        - RuntimeError when called under pytest with project_root=None
    """
    if project_root is None:
        _refuse_implicit_root_under_pytest( "attestation_path" )
        project_root = cu.get_project_root()
    return os.path.join( project_root, ATTESTATIONS_SUBDIR, ATTESTATION_FILENAME )


# ═══════════════════════════════════════════════════════════════════════════════
# Hashing + record construction
# ═══════════════════════════════════════════════════════════════════════════════

def _sha256_text( text ):
    return hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()


def sha256_file( path ):
    """
    sha256 of a file's bytes, or None when it does not exist.

    Ensures:
        - returns None for a missing path rather than raising — a tier that
          produced no junit file must still be attestable, and a crash here would
          destroy the very record that says so
        - reads in chunks so a large log does not have to fit in memory
    """
    if path is None or not os.path.exists( path ): return None
    digest = hashlib.sha256()
    with open( path, "rb" ) as handle:
        for chunk in iter( lambda: handle.read( 65536 ), b"" ):
            digest.update( chunk )
    return digest.hexdigest()


def canonical_payload( record ):
    """
    The exact bytes a record's hash is taken over.

    Ensures:
        - `chain_sha256` is EXCLUDED (a record cannot hash its own hash)
        - keys are sorted and separators fixed, so two runs producing equal
          records produce equal hashes on any Python build
    """
    body = { k: v for k, v in record.items() if k != "chain_sha256" }
    return json.dumps( body, sort_keys=True, separators=( ",", ":" ) )


def build_record( result, suite, job_id, prev_sha256, seq, started_at, finished_at ):
    """
    Build one attestation record from a tier result dict.

    Requires:
        - result is the dict `_run_suite` returns (passed/failed/skipped/errors/
          exit_code/log_path present; extra keys ignored)
        - prev_sha256 is the previous record's chain_sha256, or GENESIS_PREV

    Ensures:
        - returns a dict carrying its own `chain_sha256`
        - counts are read explicitly, never via a defaulting getattr/get chain —
          a missing count is a defect in the caller, not something to paper over
          with a zero that reads exactly like a real zero
    """
    record = {
        "seq"           : seq,
        "job_id"        : job_id,
        "suite"         : suite,
        "started_at"    : started_at,
        "finished_at"   : finished_at,
        "exit_code"     : result[ "exit_code" ],
        "passed"        : result[ "passed"  ],
        "failed"        : result[ "failed"  ],
        "skipped"       : result[ "skipped" ],
        "errors"        : result[ "errors"  ],
        "log_path"      : result.get( "log_path" ),
        "log_sha256"    : sha256_file( result.get( "log_path" ) ),
        "junit_path"    : result.get( "junit_path" ),
        "junit_sha256"  : sha256_file( result.get( "junit_path" ) ),
        "prev_sha256"   : prev_sha256,
    }
    record[ "chain_sha256" ] = _sha256_text( canonical_payload( record ) )
    return record


# ═══════════════════════════════════════════════════════════════════════════════
# Append + verify
# ═══════════════════════════════════════════════════════════════════════════════

def read_records( path ):
    """
    Every record in the ledger, in file order.

    Ensures:
        - returns [] when the file does not exist
        - a malformed line RAISES rather than being skipped: silently dropping an
          unparseable record would let a corrupted ledger verify clean, which is
          the failure this module exists to prevent
    """
    if not os.path.exists( path ): return []
    records = []
    with open( path, "r" ) as handle:
        for lineno, line in enumerate( handle, start=1 ):
            line = line.strip()
            if not line: continue
            try:
                records.append( json.loads( line ) )
            except json.JSONDecodeError as e:
                raise ValueError( f"{path}:{lineno} is not valid JSON — the ledger is corrupt, not empty: {e}" )
    return records


def append_attestation( result, suite, job_id, started_at, finished_at, path=None, project_root=None ):
    """
    Append one attestation record, chained to whatever is already there.

    Requires:
        - result carries the five count/exit keys build_record reads

    Ensures:
        - creates the parent directory if absent
        - links to the last record's chain_sha256, or GENESIS_PREV when first
        - opens with "a" so a concurrent writer cannot truncate the ledger
        - returns the record that was written
    """
    target = path if path is not None else attestation_path( project_root )
    os.makedirs( os.path.dirname( target ), exist_ok=True )

    existing = read_records( target )
    prev     = existing[ -1 ][ "chain_sha256" ] if existing else GENESIS_PREV
    record   = build_record(
        result      = result,
        suite       = suite,
        job_id      = job_id,
        prev_sha256 = prev,
        seq         = len( existing ),
        started_at  = started_at,
        finished_at = finished_at,
    )
    with open( target, "a" ) as handle:
        handle.write( json.dumps( record, sort_keys=True, separators=( ",", ":" ) ) + "\n" )
    return record


def verify_chain( path ):
    """
    Walk the ledger and report the FIRST index where the chain breaks.

    Ensures:
        - status "no_records" for an absent or empty ledger — NEVER "valid".
          An empty store and a healthy store must not read alike; that
          equivalence is the defect this row was filed about.
        - status "valid" only when every record's recomputed hash matches and
          every prev_sha256 matches its predecessor
        - status "broken" carries `first_broken_index` and a `reason`
        - verification is independent of the writer: it recomputes hashes from
          the payload rather than trusting the stored value
    """
    records = read_records( path )
    if not records:
        return { "status" : "no_records", "count" : 0 }

    expected_prev = GENESIS_PREV
    for index, record in enumerate( records ):
        if record.get( "prev_sha256" ) != expected_prev:
            return {
                "status"             : "broken",
                "count"              : len( records ),
                "first_broken_index" : index,
                "reason"             : "prev_sha256 does not match the preceding record — a record was edited, removed, or reordered",
            }
        recomputed = _sha256_text( canonical_payload( record ) )
        if recomputed != record.get( "chain_sha256" ):
            return {
                "status"             : "broken",
                "count"              : len( records ),
                "first_broken_index" : index,
                "reason"             : "chain_sha256 does not match the record's own contents — this record was edited in place",
            }
        expected_prev = record[ "chain_sha256" ]

    return { "status" : "valid", "count" : len( records ) }
