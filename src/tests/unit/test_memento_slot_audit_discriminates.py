"""
The memento slot audit must SEPARATE its causes, not merely notice them.

Row b0f60712. A path-vs-header disagreement has at least four causes that print
identically — a writer defect, a hand-writer's typo, `slot=tmp` (outside the repo by
design), and legacy schema drift (`slot=persona`). The whole value of this classifier
is that it does NOT collapse them into one "mismatch" bucket, so the tests that matter
are the ones proving the buckets are DISTINCT.

A test that only asserts "a bad file is flagged" would pass against a classifier that
flags everything. `test_the_four_causes_land_in_four_different_verdicts` is the arm
that catches that, and it is the reason the rest of this file is worth reading.
"""

import pytest

from lupin_mcp.memento_slot_audit import (
    verdict_for, audit_one, render_report,
    AGREE, MISMATCH, EXEMPT_TMP, EXEMPT_MIRROR,
    UNRECOGNISED_VOCABULARY, NO_DECLARATION, UNRESOLVED, UNKNOWN_PLACEMENT,
    ACTIONABLE,
)


# ── The bridge between the two vocabularies ──────────────────────────────────

@pytest.mark.parametrize( "declared, actual", [
    ( "io",   "repo_io" ),   # THE ONE A NAIVE `declared == actual` GETS WRONG
    ( "root", "root"    ),
] )
def test_a_correctly_filed_record_agrees_across_the_two_vocabularies( declared, actual ):
    verdict, detail = verdict_for( declared, actual )
    assert verdict == AGREE
    assert declared in detail and actual in detail


def test_io_and_repo_io_are_the_same_slot_and_a_string_compare_would_deny_it():
    # The negative control for the bridge: if someone "simplifies" _DECLARED_TO_ACTUAL
    # into `declared == actual`, this pair stops agreeing and this test reddens.
    assert verdict_for( "io", "repo_io" )[ 0 ] == AGREE
    assert "io" != "repo_io"


# ── The one verdict that means "go and look" ─────────────────────────────────

@pytest.mark.parametrize( "declared, actual", [
    ( "io",   "root"    ),   # the direction of this row's own specimen
    ( "root", "repo_io" ),   # the direction seen 3x in the fleet survey
] )
def test_a_genuinely_misfiled_record_is_a_mismatch( declared, actual ):
    verdict, detail = verdict_for( declared, actual )
    assert verdict == MISMATCH
    assert "INVESTIGATE" in detail
    # It must say it CANNOT separate writer-defect from hand-typo, because it cannot.
    assert "cannot tell you which" in detail


# ── The benign causes, each in its OWN bucket ────────────────────────────────

@pytest.mark.parametrize( "actual", [ "root", "repo_io", "unknown", "mirror", None ] )
def test_tmp_is_exempt_whatever_its_placement( actual ):
    # tmp lands outside the repo by construction, so it can never match. A classifier
    # that reported it as a mismatch would fire on every legitimate tmp record.
    verdict, _ = verdict_for( "tmp", actual )
    assert verdict == EXEMPT_TMP


@pytest.mark.parametrize( "declared", [ "persona", "canonical" ] )
def test_dead_vocabulary_is_schema_drift_not_a_mismatch( declared ):
    # Both values were found in the live corpus. They want a MIGRATION, not an
    # investigation, and folding them into MISMATCH is what makes a count meaningless.
    verdict, detail = verdict_for( declared, "repo_io" )
    assert verdict == UNRECOGNISED_VOCABULARY
    assert "migration" in detail


def test_a_mirror_copy_is_a_legitimate_placement():
    assert verdict_for( "root", "mirror" )[ 0 ] == EXEMPT_MIRROR


@pytest.mark.parametrize( "declared", [ None, "", "   " ] )
def test_a_file_with_nothing_declared_is_not_a_mismatch( declared ):
    # A header-less file is a file with nothing to compare — reporting it as a
    # disagreement would blame the audit's own blind spot on the file.
    verdict, _ = verdict_for( declared, "root" )
    assert verdict == NO_DECLARATION


@pytest.mark.parametrize( "actual", [ None, "none" ] )
def test_an_unresolved_placement_is_its_own_verdict( actual ):
    assert verdict_for( "root", actual )[ 0 ] == UNRESOLVED


# ── The fifth placement, which used to ride inside MISMATCH ──────────────────

@pytest.mark.parametrize( "declared", [ "io", "root" ] )
def test_a_placement_under_no_known_root_is_its_own_verdict( declared ):
    # `classify_memento_slot` really returns "unknown" — resolved, but under none of
    # the roots it knows. It is NOT "nothing resolved", so folding it into UNRESOLVED
    # would be the same collapse one step over.
    verdict, detail = verdict_for( declared, "unknown" )
    assert verdict == UNKNOWN_PLACEMENT
    assert "NOT a writer investigation" in detail


def test_an_unknown_placement_is_not_reported_as_a_misfiled_record():
    # 🔴 THE ARM THAT CARRIES THE FINDING. Before SLOT_UNKNOWN was imported, "unknown"
    # matched no branch and fell through to MISMATCH — indistinguishable from a genuine
    # writer defect, and pointing the reader at the wrong remedy. Collapse the two back
    # together and this reddens; every other test in this file stays green.
    misfiled = verdict_for( "io", "root"    )[ 0 ]
    unknown  = verdict_for( "io", "unknown" )[ 0 ]
    assert unknown  == UNKNOWN_PLACEMENT
    assert misfiled == MISMATCH
    assert unknown != misfiled


def test_an_unknown_placement_is_not_folded_into_unresolved_either():
    # The OTHER collapse available to someone tidying this up. "no path resolved" and
    # "resolved somewhere we do not recognise" want different remedies.
    assert verdict_for( "root", "unknown" )[ 0 ] != verdict_for( "root", "none" )[ 0 ]


# ── 🔴 THE ARM THAT CARRIES THE FINDING ──────────────────────────────────────

def test_the_four_causes_land_in_four_different_verdicts():
    """
    The discrimination proof. Collapse any two of these into one bucket and this
    reddens, while every single-case test above would stay green.
    """
    writer_or_typo = verdict_for( "io",        "root"    )[ 0 ]   # (a)/(b) — unseparable
    by_design      = verdict_for( "tmp",       "unknown" )[ 0 ]   # (c)
    schema_drift   = verdict_for( "persona",   "repo_io" )[ 0 ]   # (d)
    fine           = verdict_for( "io",        "repo_io" )[ 0 ]

    assert len( { writer_or_typo, by_design, schema_drift, fine } ) == 4


def test_only_the_causes_that_want_a_human_are_actionable():
    # tmp, mirror, schema-less and unresolved must NOT summon anybody.
    assert MISMATCH                in ACTIONABLE
    assert UNRECOGNISED_VOCABULARY in ACTIONABLE
    # A SPLIT, NOT AN ADDITION: "unknown" already summoned a human, by riding inside
    # MISMATCH. Dropping it from ACTIONABLE while giving it its own name would have
    # silently RETIRED a signal under cover of clarifying it.
    assert UNKNOWN_PLACEMENT       in ACTIONABLE
    for benign in ( AGREE, EXEMPT_TMP, EXEMPT_MIRROR, NO_DECLARATION, UNRESOLVED ):
        assert benign not in ACTIONABLE


# ── audit_one: the wiring ────────────────────────────────────────────────────

def test_audit_one_reports_an_unreadable_file_rather_than_dying():
    finding = audit_one(
        "/nowhere.md", "/repo",
        read_text_fn    = lambda p: None,
        parse_header_fn = lambda t: {},
        classify_fn     = lambda p, r: "root",
    )
    assert finding[ "verdict" ]    == NO_DECLARATION
    assert finding[ "actionable" ] is False
    assert "could not be read" in finding[ "detail" ]


def test_audit_one_carries_both_values_into_the_finding():
    finding = audit_one(
        "/repo/.claude-memento-x.md", "/repo",
        read_text_fn    = lambda p: "body",
        parse_header_fn = lambda t: { "slot": "io" },
        classify_fn     = lambda p, r: "root",
    )
    assert finding[ "declared" ]   == "io"
    assert finding[ "actual" ]     == "root"
    assert finding[ "verdict" ]    == MISMATCH
    assert finding[ "actionable" ] is True


def test_audit_one_survives_a_parser_returning_none():
    finding = audit_one(
        "/repo/x.md", "/repo",
        read_text_fn    = lambda p: "body",
        parse_header_fn = lambda t: None,
        classify_fn     = lambda p, r: "root",
    )
    assert finding[ "verdict" ] == NO_DECLARATION


# ── render_report: named files, never a defect count ─────────────────────────

def test_an_empty_scan_says_so_loudly_instead_of_reading_as_clean():
    # An empty result and a clean result are two different failures wearing one face.
    lines = render_report( [] )
    assert any( "NOTHING SCANNED" in l for l in lines )


def test_the_report_names_every_actionable_file_individually():
    findings = [
        audit_one( "/repo/bad.md",  "/repo", lambda p: "b", lambda t: { "slot": "io" },      lambda p, r: "root"    ),
        audit_one( "/repo/old.md",  "/repo", lambda p: "b", lambda t: { "slot": "persona" }, lambda p, r: "repo_io" ),
        audit_one( "/repo/fine.md", "/repo", lambda p: "b", lambda t: { "slot": "io" },      lambda p, r: "repo_io" ),
    ]
    text = "\n".join( render_report( findings ) )
    assert "/repo/bad.md"  in text
    assert "/repo/old.md"  in text
    assert "/repo/fine.md" not in text          # agreeing files are not named
    assert "3 file(s) scanned" in text          # the corpus size is stated


def test_the_report_refuses_to_print_a_single_defect_count():
    findings = [
        audit_one( "/r/a.md", "/r", lambda p: "b", lambda t: { "slot": "io" },      lambda p, r: "root"    ),
        audit_one( "/r/b.md", "/r", lambda p: "b", lambda t: { "slot": "persona" }, lambda p, r: "repo_io" ),
    ]
    text = "\n".join( render_report( findings ) )
    # The two causes are tallied SEPARATELY and the census disclaims being a total.
    assert "NOT a defect count" in text
    assert MISMATCH                in text
    assert UNRECOGNISED_VOCABULARY in text


def test_a_clean_corpus_still_states_its_size():
    findings = [ audit_one( "/r/a.md", "/r", lambda p: "b", lambda t: { "slot": "root" }, lambda p, r: "root" ) ]
    text = "\n".join( render_report( findings ) )
    assert "nothing to investigate" in text
    assert "1 file(s) scanned"      in text


# ── 🔴 THE LAYER THE INCIDENT ENTERED AT: real file, real readers ────────────

def test_a_real_misfiled_record_on_disk_is_caught_by_the_real_readers( tmp_path ):
    """
    The incident was a real memento on a real path read by the real parser, so this
    drives both production readers rather than the injected fakes above.
    """
    from lupin_mcp.reap_memento import parse_memento_header
    from cosa.agents.heartbeat_arbiter.respin_wake_check import classify_memento_slot

    repo = tmp_path / "repo"
    ( repo / "io" / "mementos" ).mkdir( parents=True )

    header = "<!-- memento-record: persona=cheech session_id=8047f2a2 written_at=2026-09-04T17:19:51-04:00 slot={} -->"

    # This row's own specimen shape: declared io, sitting at the repo ROOT.
    misfiled = repo / ".claude-memento-cheech.md"
    misfiled.write_text( header.format( "io" ) + "\n# body\n" )

    # The control — same header machinery, filed where it says. Without this arm a
    # classifier that flagged EVERY file would pass the assertion above it.
    correct = repo / "io" / "mementos" / "cheech-8047f2a2.md"
    correct.write_text( header.format( "io" ) + "\n# body\n" )

    def read( p ): return open( p, encoding="utf-8" ).read()

    bad  = audit_one( str( misfiled ), str( repo ), read, parse_memento_header, classify_memento_slot )
    good = audit_one( str( correct  ), str( repo ), read, parse_memento_header, classify_memento_slot )

    assert bad[ "verdict" ]  == MISMATCH,  bad[ "detail" ]
    assert good[ "verdict" ] == AGREE,     good[ "detail" ]
