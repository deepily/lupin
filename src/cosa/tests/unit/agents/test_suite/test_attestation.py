"""
Unit coverage for the tier-run attestation ledger (row 691d49db).

⚠️ SCOPE, STATED SO A GREEN RUN IS NOT OVER-READ
------------------------------------------------
These tests prove the CHAIN LOGIC: that an append links to its predecessor, that
an edit or a deletion is detected and localized, and that an empty ledger reports
"no records" rather than "valid".

They do NOT prove the writer is wired into a real tier run. That is the 0→N
calibration, it requires observing the store fill on a live run, and it is owed
separately — the instrument cannot be attested by the thing it exists to attest.
A fully green file here is compatible with a ledger nothing ever writes to.

Everything runs from `tmp_path`. No tier, no container, no server, no network.
"""

import json

import pytest

from cosa.agents.test_suite import attestation as att


def _result( exit_code=0, passed=10, failed=0, skipped=1, errors=0, log_path=None, junit_path=None ):
    return {
        "exit_code"  : exit_code,
        "passed"     : passed,
        "failed"     : failed,
        "skipped"    : skipped,
        "errors"     : errors,
        "log_path"   : log_path,
        "junit_path" : junit_path,
    }


def _append( path, n=1, suite="unit" ):
    written = []
    for i in range( n ):
        written.append( att.append_attestation(
            result      = _result( passed=10 + i ),
            suite       = suite,
            job_id      = f"ts-{i:08x}",
            started_at  = f"2026-07-27T10:{i:02d}:00Z",
            finished_at = f"2026-07-27T10:{i:02d}:30Z",
            path        = str( path ),
        ) )
    return written


# ---------------------------------------------------------------------------
# The rule Mr Radio is holding this to: unknown must not fold into a green.
# ---------------------------------------------------------------------------

def test_absent_ledger_reports_no_records_not_valid( tmp_path ):
    """An absent store is UNKNOWN. Reporting 'valid' would be the whole defect."""
    verdict = att.verify_chain( str( tmp_path / "nope.jsonl" ) )
    assert verdict[ "status" ] == "no_records"
    assert verdict[ "status" ] != "valid"
    assert verdict[ "count"  ] == 0


def test_empty_ledger_reports_no_records_not_valid( tmp_path ):
    """A file that exists but holds nothing is equally unknown."""
    path = tmp_path / "ledger.jsonl"
    path.write_text( "" )
    assert att.verify_chain( str( path ) )[ "status" ] == "no_records"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_first_record_chains_to_genesis( tmp_path ):
    path = tmp_path / "ledger.jsonl"
    record = _append( path )[ 0 ]
    assert record[ "prev_sha256" ] == att.GENESIS_PREV
    assert record[ "seq" ] == 0


def test_appends_chain_to_their_predecessor( tmp_path ):
    path    = tmp_path / "ledger.jsonl"
    written = _append( path, n=4 )
    for earlier, later in zip( written, written[ 1: ] ):
        assert later[ "prev_sha256" ] == earlier[ "chain_sha256" ]
    assert att.verify_chain( str( path ) ) == { "status" : "valid", "count" : 4 }


def test_appending_never_truncates_what_is_already_there( tmp_path ):
    path = tmp_path / "ledger.jsonl"
    _append( path, n=2 )
    _append( path, n=1 )
    assert att.verify_chain( str( path ) )[ "count" ] == 3


# ---------------------------------------------------------------------------
# CONTROLS THAT MUST FAIL — a verifier that always said "valid" would sail
# through every test above.
# ---------------------------------------------------------------------------

def test_an_edited_record_is_detected_and_localized( tmp_path ):
    """Edit a middle record's payload in place: the chain must break AT it."""
    path = tmp_path / "ledger.jsonl"
    _append( path, n=5 )

    lines  = path.read_text().splitlines()
    record = json.loads( lines[ 2 ] )
    record[ "passed" ] = 99999                       # the lie
    lines[ 2 ] = json.dumps( record, sort_keys=True, separators=( ",", ":" ) )
    path.write_text( "\n".join( lines ) + "\n" )

    verdict = att.verify_chain( str( path ) )
    assert verdict[ "status" ] == "broken"
    assert verdict[ "first_broken_index" ] == 2
    assert "edited in place" in verdict[ "reason" ]


def test_a_deleted_record_is_detected_and_localized( tmp_path ):
    """Remove a middle record: the successor's prev_sha256 no longer matches."""
    path = tmp_path / "ledger.jsonl"
    _append( path, n=5 )

    lines = path.read_text().splitlines()
    del lines[ 2 ]
    path.write_text( "\n".join( lines ) + "\n" )

    verdict = att.verify_chain( str( path ) )
    assert verdict[ "status" ] == "broken"
    assert verdict[ "first_broken_index" ] == 2
    assert "edited, removed, or reordered" in verdict[ "reason" ]


def test_reordered_records_are_detected( tmp_path ):
    path = tmp_path / "ledger.jsonl"
    _append( path, n=4 )
    lines = path.read_text().splitlines()
    lines[ 1 ], lines[ 2 ] = lines[ 2 ], lines[ 1 ]
    path.write_text( "\n".join( lines ) + "\n" )
    assert att.verify_chain( str( path ) )[ "status" ] == "broken"


def test_a_truncated_tail_still_verifies_but_a_forged_head_does_not( tmp_path ):
    """
    Dropping the LAST record leaves a shorter but internally consistent chain —
    that is honest truncation and cannot be detected from the ledger alone, so
    the verifier must not pretend otherwise. Dropping the FIRST one breaks it.
    """
    path = tmp_path / "ledger.jsonl"
    _append( path, n=4 )
    lines = path.read_text().splitlines()

    path.write_text( "\n".join( lines[ :-1 ] ) + "\n" )
    assert att.verify_chain( str( path ) ) == { "status" : "valid", "count" : 3 }

    path.write_text( "\n".join( lines[ 1: ] ) + "\n" )
    assert att.verify_chain( str( path ) )[ "first_broken_index" ] == 0


def test_a_corrupt_line_raises_instead_of_reading_as_empty( tmp_path ):
    """
    A ledger that cannot be parsed is CORRUPT, not empty. Skipping the bad line
    would let a mangled store verify clean — the same shape as an empty store
    reading as valid.
    """
    path = tmp_path / "ledger.jsonl"
    _append( path, n=2 )
    with open( path, "a" ) as handle:
        handle.write( "{not json at all\n" )

    with pytest.raises( ValueError ) as exc:
        att.verify_chain( str( path ) )
    assert "corrupt, not empty" in str( exc.value )


# ---------------------------------------------------------------------------
# Hashing details
# ---------------------------------------------------------------------------

def test_chain_hash_excludes_itself( tmp_path ):
    """A record cannot hash its own hash — the payload must omit chain_sha256."""
    record = _append( tmp_path / "ledger.jsonl" )[ 0 ]
    assert "chain_sha256" not in att.canonical_payload( record )


def test_artifact_digests_are_recorded_when_the_files_exist( tmp_path ):
    log   = tmp_path / "run.log";  log.write_text( "hello" )
    junit = tmp_path / "run.xml";  junit.write_text( "<testsuite/>" )
    record = att.append_attestation(
        result      = _result( log_path=str( log ), junit_path=str( junit ) ),
        suite       = "integration", job_id="ts-deadbeef",
        started_at  = "s", finished_at="f", path=str( tmp_path / "ledger.jsonl" ),
    )
    assert record[ "log_sha256"   ] == att.sha256_file( str( log ) )
    assert record[ "junit_sha256" ] == att.sha256_file( str( junit ) )


def test_a_missing_artifact_records_none_rather_than_exploding( tmp_path ):
    """
    A tier that produced no junit file must still be ATTESTABLE. Raising here
    would destroy the very record that says the run went wrong.
    """
    record = att.append_attestation(
        result      = _result( exit_code=1, junit_path=str( tmp_path / "never-written.xml" ) ),
        suite       = "unit", job_id="ts-cafe", started_at="s", finished_at="f",
        path        = str( tmp_path / "ledger.jsonl" ),
    )
    assert record[ "junit_sha256" ] is None
    assert att.verify_chain( str( tmp_path / "ledger.jsonl" ) )[ "status" ] == "valid"


def test_roots_hang_off_the_io_bind_mount():
    """
    The durable home is `io/`, which docker inspect confirms is a bind mount on
    the test container. A root under /tmp or inside the image would reintroduce
    the exact ephemerality this module exists to fix.
    """
    assert att.ARTIFACTS_SUBDIR.startswith( "io/" )
    assert att.ATTESTATIONS_SUBDIR.startswith( "io/" )
    assert att.artifact_root( "/var/lupin" )    == "/var/lupin/io/test-suite/artifacts"
    assert att.attestation_path( "/var/lupin" ) == "/var/lupin/io/test-suite/attestations/tier-runs.jsonl"


def test_blank_lines_are_skipped_without_breaking_the_chain( tmp_path ):
    """
    A trailing newline or a stray blank line is formatting, not a record. It must
    not be read as an empty record (which would break the chain) nor raise as
    corrupt (which would make a harmless whitespace edit look like tampering).
    """
    path = tmp_path / "ledger.jsonl"
    _append( path, n=3 )

    lines = path.read_text().splitlines()
    path.write_text( lines[ 0 ] + "\n\n" + lines[ 1 ] + "\n   \n" + lines[ 2 ] + "\n\n" )

    assert att.verify_chain( str( path ) ) == { "status" : "valid", "count" : 3 }


# ---------------------------------------------------------------------------
# FAIL-CLOSED under pytest — the arm that closes the mode a static AST scan
# structurally cannot see (fd0cd863: the tests named no path; production code
# computed it). Krishna took the test_job.py coupling knowingly.
# ---------------------------------------------------------------------------

def test_artifact_root_refuses_the_real_root_under_pytest():
    """
    THE CONTROL THAT MUST FAIL if the refusal is removed.

    Predicted failure when the guard is deleted: no exception is raised, so
    pytest.raises reports DID NOT RAISE — and the returned path would be the
    real /var/lupin artifact root.
    """
    with pytest.raises( RuntimeError ) as exc:
        att.artifact_root()
    assert "without an explicit `project_root`" in str( exc.value )
    assert "tmp_path" in str( exc.value )


def test_attestation_path_refuses_the_real_ledger_under_pytest():
    """Both entry points, not just the one someone remembered."""
    with pytest.raises( RuntimeError ) as exc:
        att.attestation_path()
    assert "attestation_path" in str( exc.value )


def test_an_explicit_root_is_always_honored( tmp_path ):
    """
    THE OTHER DIRECTION. A refusal that fired unconditionally would pass both
    tests above while making the module unusable — this is the arm that catches
    a guard which blocks the legitimate path too.
    """
    assert att.artifact_root( str( tmp_path ) ).startswith( str( tmp_path ) )
    assert att.attestation_path( str( tmp_path ) ).startswith( str( tmp_path ) )


def test_outside_pytest_the_real_root_resolves( monkeypatch ):
    """
    PREMISE: production must still work. Simulated by clearing the marker the
    guard keys on — if this ever fails, the guard has stopped being conditional
    and is refusing the orchestrator itself.
    """
    monkeypatch.delenv( "PYTEST_CURRENT_TEST", raising=False )
    assert att.artifact_root().endswith( att.ARTIFACTS_SUBDIR )
    assert att.attestation_path().endswith( att.ATTESTATION_FILENAME )


# ---------------------------------------------------------------------------
# THE WIRING — row 691d49db's 0→N, at unit scale.
#
# ⚠️ This is NOT the calibration the row owes. The row requires the ledger
# observed going 0→N on a REAL scheduled tier. What these prove is narrower and
# worth stating: that `_run_suite`'s call site reaches the writer at all, and
# that a failure to record cannot fail the run it records. An unwired writer and
# a wired one are indistinguishable without the first of these.
# ---------------------------------------------------------------------------

def test_a_tier_run_appends_exactly_one_record( tmp_path, monkeypatch ):
    """0 -> 1. The ledger is empty, one tier runs, one chained record exists."""
    from cosa.agents.test_suite.job import TestSuiteJob

    monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )
    job = TestSuiteJob.__new__( TestSuiteJob )
    job.id_hash = "ts-wired01"

    ledger = tmp_path / att.ATTESTATIONS_SUBDIR / att.ATTESTATION_FILENAME
    assert att.verify_chain( str( ledger ) )[ "status" ] == "no_records"

    job._attest_tier_run( "unit", _result( passed=7 ), "2026-07-27T10:00:00Z" )

    verdict = att.verify_chain( str( ledger ) )
    assert verdict == { "status" : "valid", "count" : 1 }
    rec = att.read_records( str( ledger ) )[ 0 ]
    assert rec[ "suite" ] == "unit" and rec[ "job_id" ] == "ts-wired01" and rec[ "passed" ] == 7


def test_successive_tier_runs_chain( tmp_path, monkeypatch ):
    """0 -> N, and the chain holds across suites the way a real job runs them."""
    from cosa.agents.test_suite.job import TestSuiteJob

    monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )
    job = TestSuiteJob.__new__( TestSuiteJob )
    job.id_hash = "ts-wired02"

    for suite in ( "unit", "smoke", "integration" ):
        job._attest_tier_run( suite, _result(), "2026-07-27T10:00:00Z" )

    ledger = tmp_path / att.ATTESTATIONS_SUBDIR / att.ATTESTATION_FILENAME
    assert att.verify_chain( str( ledger ) ) == { "status" : "valid", "count" : 3 }
    assert [ r[ "suite" ] for r in att.read_records( str( ledger ) ) ] == [ "unit", "smoke", "integration" ]


def test_a_failing_attestation_never_fails_the_run( tmp_path, monkeypatch, capsys ):
    """
    CONTROL. The receipt exists FOR runs that go wrong, so a recorder that can
    abort the run would delete the evidence in exactly the case it is for.
    """
    from cosa.agents.test_suite.job import TestSuiteJob

    monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )
    monkeypatch.setattr( att, "append_attestation",
                         lambda **kw: ( _ for _ in () ).throw( OSError( "disk full" ) ) )
    job = TestSuiteJob.__new__( TestSuiteJob )
    job.id_hash = "ts-wired03"

    job._attest_tier_run( "unit", _result(), "2026-07-27T10:00:00Z" )   # must NOT raise

    err = capsys.readouterr().out
    assert "attestation FAILED" in err and "disk full" in err
    assert "run itself is unaffected" in err


def test_a_test_pinned_artifact_dir_keeps_the_ledger_out_of_the_live_root( tmp_path, monkeypatch ):
    """
    The wiring inherits the fail-closed contract: a test that pinned _ARTIFACT_DIR
    writes its ledger there, never into the real `io/`.
    """
    from cosa.agents.test_suite.job import TestSuiteJob

    monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )
    job = TestSuiteJob.__new__( TestSuiteJob )
    job.id_hash = "ts-wired04"
    job._attest_tier_run( "unit", _result(), "2026-07-27T10:00:00Z" )

    assert ( tmp_path / att.ATTESTATIONS_SUBDIR / att.ATTESTATION_FILENAME ).exists()
