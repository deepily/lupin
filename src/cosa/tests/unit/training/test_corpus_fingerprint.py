"""
Tests for the training-dataset freshness guard (row 11390b57).

The three cases the row demands are marked PROOF CASE 1/2/3 below:
  1. RED FIRST      — a corpus change after generation makes the run REFUSE.
  2. NEGATIVE CTRL  — nothing changes, the run PROCEEDS, so the guard is not
                      "always refuse" wearing a guard's clothes.
  3. DIRECTION      — the refusal says WHICH SIDE is stale, not merely that the
                      two sides differ.
"""
import json
import os

import pytest

import cosa.training.corpus_fingerprint as cf
from cosa.training.xml_coordinator import XmlCoordinator


# ── Fixture: a miniature project root with real manifest filenames ────────────

CORPUS_DIR_REL = "/src/ephemera/prompts/data"


def _write( path, text ):
    os.makedirs( os.path.dirname( path ), exist_ok=True )
    with open( path, "w" ) as f:
        f.write( text )


@pytest.fixture
def project_root( tmp_path ):
    """
    Build a throwaway project root carrying every manifest the guard reads.

    Each manifest names one small corpus file, so a single edit is enough to
    move exactly one file's hash.
    """
    root = str( tmp_path )

    for i, manifest_rel in enumerate( cf.PLAIN_MANIFESTS ):
        corpus_rel = f"{CORPUS_DIR_REL}/corpus-plain-{i}.txt"
        _write( root + corpus_rel, f"# a comment, invisible to the loader\nline a{i}\n\nline b{i}\n" )
        _write( root + manifest_rel, json.dumps( { f"command {i}": corpus_rel } ) )

    for i, manifest_rel in enumerate( cf.ENRICHED_MANIFESTS ):
        template_rel = f"{CORPUS_DIR_REL}/templates-{i}.txt"
        _write( root + template_rel, f"# header\ntemplate {i}\n" )
        _write( root + manifest_rel, json.dumps( { f"agentic {i}": { "template_file": template_rel, "placeholders": {} } } ) )

    return root


def _make_artifacts( root ):
    for filename in cf.ARTIFACT_FILENAMES:
        _write( root + CORPUS_DIR_REL + "/" + filename, '{"prompt": "x"}\n' )


def _generate( root, generated_at="2026-08-22T13:02:57+00:00" ):
    """Stand in for a generation run: write the artifacts, then stamp the corpus."""
    _make_artifacts( root )
    return cf.write_stamp( root, generated_at )


def _first_plain_corpus( root ):
    with open( root + cf.PLAIN_MANIFESTS[ 0 ], "r" ) as f:
        return root + list( json.load( f ).values() )[ 0 ]


# ── PROOF CASE 1 — RED FIRST ─────────────────────────────────────────────────

def test_corpus_change_after_generation_refuses( project_root ):
    """A corpus edit after generation must REFUSE, naming the mismatch."""
    _generate( project_root )

    corpus = _first_plain_corpus( project_root )
    with open( corpus, "a" ) as f:
        f.write( "line c0\n" )

    verdict, report = cf.verify( project_root )

    assert verdict == cf.VERDICT_MISMATCH
    assert cf.VERDICT_EXIT_CODES[ verdict ] == cf.EXIT_REFUSE
    assert "CORPUS FINGERPRINT MISMATCH" in report
    assert "refusing to train" in report


def test_corpus_deletion_after_generation_refuses( project_root ):
    """Removing lines is a change too — the guard is not append-only."""
    _generate( project_root )

    corpus = _first_plain_corpus( project_root )
    _write( corpus, "# a comment, invisible to the loader\nline a0\n" )

    verdict, _ = cf.verify( project_root )

    assert verdict == cf.VERDICT_MISMATCH


def test_agentic_template_change_refuses( project_root ):
    """The enriched manifest's template files are guarded too, not just the plain ones."""
    _generate( project_root )

    with open( project_root + cf.ENRICHED_MANIFESTS[ 0 ], "r" ) as f:
        template = project_root + list( json.load( f ).values() )[ 0 ][ "template_file" ]
    with open( template, "a" ) as f:
        f.write( "template extra\n" )

    verdict, _ = cf.verify( project_root )

    assert verdict == cf.VERDICT_MISMATCH


# ── PROOF CASE 2 — NEGATIVE CONTROL ──────────────────────────────────────────

def test_unchanged_corpus_proceeds( project_root ):
    """Nothing changes → the run PROCEEDS. The guard is not always-refuse."""
    _generate( project_root )

    verdict, report = cf.verify( project_root )

    assert verdict == cf.VERDICT_MATCH
    assert cf.VERDICT_EXIT_CODES[ verdict ] == cf.EXIT_OK
    assert "matches" in report


def test_comment_edit_alone_still_proceeds( project_root ):
    """
    A comment edit cannot reach training, so it must not refuse.

    This is the loader-visible projection earning its keep: a raw-bytes hash
    would refuse here, and a false refusal on a P1 path is how a guard gets
    switched off.
    """
    _generate( project_root )

    corpus = _first_plain_corpus( project_root )
    _write( corpus, "# a COMPLETELY REWRITTEN comment\n\n\nline a0\n\nline b0\n" )

    verdict, _ = cf.verify( project_root )

    assert verdict == cf.VERDICT_MATCH


def test_trailing_whitespace_alone_still_proceeds( project_root ):
    """clean=True strips lines, so indentation churn must not refuse either."""
    _generate( project_root )

    corpus = _first_plain_corpus( project_root )
    _write( corpus, "# a comment, invisible to the loader\n   line a0   \n\n\tline b0\t\n" )

    verdict, _ = cf.verify( project_root )

    assert verdict == cf.VERDICT_MATCH


def test_regenerating_after_a_change_clears_the_refusal( project_root ):
    """The remedy the refusal recommends actually works."""
    _generate( project_root )

    corpus = _first_plain_corpus( project_root )
    with open( corpus, "a" ) as f:
        f.write( "line c0\n" )
    assert cf.verify( project_root )[ 0 ] == cf.VERDICT_MISMATCH

    _generate( project_root, generated_at="2026-08-25T18:00:00+00:00" )

    assert cf.verify( project_root )[ 0 ] == cf.VERDICT_MATCH


# ── PROOF CASE 3 — DIRECTION ─────────────────────────────────────────────────

def test_refusal_names_which_side_grew( project_root ):
    """
    The refusal must say the corpus on disk GREW relative to what the dataset
    was built from — not merely that the two disagree.
    """
    stamp  = _generate( project_root )
    corpus = _first_plain_corpus( project_root )
    with open( corpus, "a" ) as f:
        f.write( "line c0\nline d0\n" )

    _, report = cf.verify( project_root )

    assert "ARTIFACT-SIDE" in report
    assert "CORPUS-SIDE" in report
    assert "the corpus on disk has 2 MORE loader-visible lines than the corpus this dataset was built from" in report
    # Both hashes appear, each labelled, so neither side has to be guessed.
    assert stamp[ "corpus_hash" ] in report
    assert cf.compute_fingerprint( project_root )[ "corpus_hash" ] in report
    assert "2026-08-22T13:02:57+00:00" in report
    # ARTIFACT-SIDE carries the smaller count; CORPUS-SIDE the larger.
    assert "ARTIFACT-SIDE  2 loader-visible lines" in report
    assert "CORPUS-SIDE    4 loader-visible lines" in report


def test_refusal_names_which_side_shrank( project_root ):
    """The 08-22 near-miss direction: the corpus on disk is the SMALLER side."""
    _generate( project_root )

    corpus = _first_plain_corpus( project_root )
    _write( corpus, "# a comment, invisible to the loader\nline a0\n" )

    _, report = cf.verify( project_root )

    assert "the corpus on disk has 1 FEWER loader-visible lines than the corpus this dataset was built from" in report
    assert "ARTIFACT-SIDE  2 loader-visible lines" in report
    assert "CORPUS-SIDE    1 loader-visible lines" in report


def test_refusal_names_an_in_place_edit( project_root ):
    """Same line count on both sides is still a direction statement, not a shrug."""
    _generate( project_root )

    corpus = _first_plain_corpus( project_root )
    _write( corpus, "# a comment, invisible to the loader\nline a0 RELABELLED\n\nline b0\n" )

    _, report = cf.verify( project_root )

    assert "same line count on both sides, so lines were edited in place" in report


def test_refusal_names_a_file_added_to_the_manifest( project_root ):
    """A newly-manifested corpus file is reported as CORPUS-SIDE only."""
    _generate( project_root )

    corpus_rel = f"{CORPUS_DIR_REL}/corpus-brand-new.txt"
    _write( project_root + corpus_rel, "brand new line\n" )
    with open( project_root + cf.PLAIN_MANIFESTS[ 0 ], "r" ) as f:
        commands = json.load( f )
    commands[ "command brand new" ] = corpus_rel
    _write( project_root + cf.PLAIN_MANIFESTS[ 0 ], json.dumps( commands ) )

    _, report = cf.verify( project_root )

    assert "ON THE CORPUS-SIDE ONLY — added to the manifest since generation: command brand new" in report


def test_refusal_names_a_file_dropped_from_the_manifest( project_root ):
    """A de-manifested corpus file is reported as ARTIFACT-SIDE only."""
    _generate( project_root )

    _write( project_root + cf.PLAIN_MANIFESTS[ 0 ], json.dumps( {} ) )

    _, report = cf.verify( project_root )

    assert "ON THE ARTIFACT-SIDE ONLY — dropped from the manifest since generation: command 0" in report


def test_refusal_survives_a_stamp_without_a_timestamp( project_root ):
    """An older stamp missing generated_at still produces a labelled report."""
    _generate( project_root )
    stamp = cf.read_stamp( project_root )
    del stamp[ "generated_at" ]
    current = cf.compute_fingerprint( project_root )
    current[ "files" ][ 0 ][ "sha256" ]     = "deadbeef"
    current[ "files" ][ 0 ][ "line_count" ] = 99

    report = cf.describe_mismatch( stamp, current )

    assert "stamped unknown time" in report


# ── The other two verdicts ───────────────────────────────────────────────────

def test_missing_artifact_asks_the_caller_to_generate( project_root ):
    """No artifact is not a refusal — it is the generate path, exit code 2."""
    verdict, report = cf.verify( project_root )

    assert verdict == cf.VERDICT_ARTIFACT_ABSENT
    assert cf.VERDICT_EXIT_CODES[ verdict ] == cf.EXIT_ARTIFACT_ABSENT
    assert "nothing to check" in report


def test_partial_artifact_counts_as_absent( project_root ):
    """All three outputs must be present, not just the train split."""
    _make_artifacts( project_root )
    os.remove( project_root + CORPUS_DIR_REL + "/" + cf.ARTIFACT_FILENAMES[ 2 ] )

    assert cf.artifact_exists( project_root ) is False
    assert cf.verify( project_root )[ 0 ] == cf.VERDICT_ARTIFACT_ABSENT


def test_artifact_without_a_stamp_refuses( project_root ):
    """A dataset predating the guard has unknown provenance, so it refuses."""
    _make_artifacts( project_root )

    verdict, report = cf.verify( project_root )

    assert verdict == cf.VERDICT_STAMP_ABSENT
    assert cf.VERDICT_EXIT_CODES[ verdict ] == cf.EXIT_REFUSE
    assert "NO CORPUS FINGERPRINT" in report
    assert cf.fingerprint_path( project_root ) in report
    # The remedy must not steer to the destructive option by reflex — an unstamped
    # dataset may well be the CORRECT side, with the corpus on disk the stale one.
    assert "Do NOT reach for generate by reflex" in report
    assert "corpus_fingerprint stamp" in report


def test_read_stamp_returns_none_when_absent( project_root ):
    assert cf.read_stamp( project_root ) is None


# ── Fingerprint mechanics ────────────────────────────────────────────────────

def test_fingerprint_is_deterministic( project_root ):
    """Hashing twice with nothing changed gives the same answer."""
    assert cf.compute_fingerprint( project_root )[ "corpus_hash" ] == cf.compute_fingerprint( project_root )[ "corpus_hash" ]


def test_fingerprint_covers_every_manifest( project_root ):
    """One entry per manifest, plain and enriched alike — no manifest silently skipped."""
    entries = cf.collect_corpus_entries( project_root )

    assert len( entries ) == len( cf.PLAIN_MANIFESTS ) + len( cf.ENRICHED_MANIFESTS )
    assert [ e[ "manifest" ] for e in entries ] == list( cf.PLAIN_MANIFESTS ) + list( cf.ENRICHED_MANIFESTS )


def test_fingerprint_counts_only_loader_visible_lines( project_root ):
    """The stamped line count is the loader's count, not the file's line count."""
    fingerprint = cf.compute_fingerprint( project_root )

    # corpus-plain-0.txt holds 4 physical lines: a comment, two content lines, one blank.
    assert fingerprint[ "files" ][ 0 ][ "line_count" ] == 2


def test_repointing_a_command_changes_the_hash( project_root ):
    """Same content under a different path is still a different corpus."""
    before = cf.compute_fingerprint( project_root )[ "corpus_hash" ]

    corpus_rel = f"{CORPUS_DIR_REL}/corpus-plain-0-moved.txt"
    _write( project_root + corpus_rel, "# a comment, invisible to the loader\nline a0\n\nline b0\n" )
    _write( project_root + cf.PLAIN_MANIFESTS[ 0 ], json.dumps( { "command 0": corpus_rel } ) )

    assert cf.compute_fingerprint( project_root )[ "corpus_hash" ] != before


def test_renaming_a_command_changes_the_hash( project_root ):
    """The command name participates, so a relabel is a change."""
    before = cf.compute_fingerprint( project_root )[ "corpus_hash" ]

    with open( project_root + cf.PLAIN_MANIFESTS[ 0 ], "r" ) as f:
        corpus_rel = list( json.load( f ).values() )[ 0 ]
    _write( project_root + cf.PLAIN_MANIFESTS[ 0 ], json.dumps( { "command renamed": corpus_rel } ) )

    assert cf.compute_fingerprint( project_root )[ "corpus_hash" ] != before


def test_loader_visible_lines_drops_comments_and_blanks( project_root ):
    corpus = _first_plain_corpus( project_root )

    assert cf._loader_visible_lines( corpus ) == [ "line a0", "line b0" ]


def test_stamp_records_its_provenance( project_root ):
    stamp = _generate( project_root )

    assert stamp[ "version" ]      == cf.FINGERPRINT_VERSION
    assert stamp[ "algo" ]         == "sha256"
    assert stamp[ "generated_at" ] == "2026-08-22T13:02:57+00:00"
    assert stamp[ "artifacts" ]    == list( cf.ARTIFACT_FILENAMES )
    assert "no shuffle" in stamp[ "projection" ]
    assert cf.read_stamp( project_root ) == stamp


def test_stamp_lands_beside_the_artifacts( project_root ):
    _generate( project_root )

    assert cf.fingerprint_path( project_root ) == project_root + CORPUS_DIR_REL + "/" + cf.FINGERPRINT_FILENAME
    assert os.path.exists( cf.fingerprint_path( project_root ) )


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_cli_verify_returns_zero_when_current( project_root, capsys ):
    _generate( project_root )

    assert cf.main( [ "verify", "--project-root", project_root ] ) == cf.EXIT_OK
    assert "matches" in capsys.readouterr().out


def test_cli_verify_returns_one_when_stale( project_root, capsys ):
    _generate( project_root )
    with open( _first_plain_corpus( project_root ), "a" ) as f:
        f.write( "line c0\n" )

    assert cf.main( [ "verify", "--project-root", project_root ] ) == cf.EXIT_REFUSE
    assert "CORPUS FINGERPRINT MISMATCH" in capsys.readouterr().out


def test_cli_verify_returns_two_when_no_artifact( project_root, capsys ):
    assert cf.main( [ "verify", "--project-root", project_root ] ) == cf.EXIT_ARTIFACT_ABSENT
    assert "nothing to check" in capsys.readouterr().out


def test_cli_stamp_writes_the_sidecar( project_root, capsys ):
    _make_artifacts( project_root )

    assert cf.main( [ "stamp", "--project-root", project_root ] ) == cf.EXIT_OK
    assert "Stamped corpus fingerprint" in capsys.readouterr().out
    assert cf.read_stamp( project_root ) is not None


def test_cli_without_a_subcommand_prints_usage( project_root, capsys ):
    assert cf.main( [ "--project-root", project_root ] ) == cf.EXIT_REFUSE
    assert "Usage:" in capsys.readouterr().out


def test_cli_falls_back_to_the_project_root( project_root, monkeypatch, capsys ):
    """Without --project-root the CLI uses the resolved project root."""
    _generate( project_root )
    monkeypatch.setattr( cf.du, "get_project_root", lambda: project_root )

    assert cf.main( [ "verify" ] ) == cf.EXIT_OK
    assert "matches" in capsys.readouterr().out


# ── Rotation: keep one previous copy before overwriting ──────────────────────

def test_rotation_keeps_the_previous_copy( tmp_path, capsys ):
    """Regeneration is irreversible and the outputs are git-ignored."""
    path = str( tmp_path / "voice-commands-xml-train.jsonl" )
    _write( path, "the good dataset" )

    kept = XmlCoordinator._rotate_previous_artifact( None, path )

    assert kept is True
    assert not os.path.exists( path )
    assert open( path + ".prev" ).read() == "the good dataset"
    assert "Kept previous copy" in capsys.readouterr().out


def test_rotation_replaces_an_older_previous_copy( tmp_path ):
    """Exactly one previous copy is kept, not an unbounded pile."""
    path = str( tmp_path / "voice-commands-xml-train.jsonl" )
    _write( path + ".prev", "two generations ago" )
    _write( path, "one generation ago" )

    XmlCoordinator._rotate_previous_artifact( None, path )

    assert open( path + ".prev" ).read() == "one generation ago"


def test_rotation_is_a_no_op_on_a_first_run( tmp_path ):
    """Nothing to keep is not an error."""
    path = str( tmp_path / "voice-commands-xml-train.jsonl" )

    assert XmlCoordinator._rotate_previous_artifact( None, path ) is False
    assert not os.path.exists( path + ".prev" )
