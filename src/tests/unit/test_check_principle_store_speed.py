"""
The old-against-new check for principle retrieval, over a tiny archive and repository.

The "old" code is the tree's own two modules committed into the temporary repository, so a clean run
must find no difference. A second commit changes one rule there, so the check must find it.
"""

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import cosa.utils.util as cu
from cosa.agents.prediction_engine.episode_view import card_text, episode_view
from cosa.research.preference_replay import scratch_db
from cosa.research.preference_replay.service_embeddings import cache_key
from cosa.rest.postgres_models import Notification, PredictionArmForecast, PreferenceEvidence, PreferencePrinciple
from scripts import check_principle_store_speed as check

ASK    = datetime( 2026, 11, 10, 12, 0, tzinfo=timezone.utc )
OWNER  = "cccccccc-0000-4000-8000-000000000001"
ENC    = "check-encoder"
EXT    = "check|v1"
VECTOR = [ 1.0 ] + [ 0.0 ] * 767


def uid( n ):
    """A UUID with letters, so SQLite does not read it as a number."""
    return uuid.UUID( f"bbbbbbbb-0000-4000-8000-{n:012d}" )


def git( repo, *arguments ):
    """Run git in the throwaway repository and return its output."""
    command = [ "git", "-C", str( repo ), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.hooksPath=/dev/null" ]
    return subprocess.run( command + list( arguments ), capture_output=True, text=True, check=True ).stdout.strip()


@pytest.fixture( scope="module" )
def repo( tmp_path_factory ):
    """A repository with the tree's two modules committed, then a commit changing one rule."""
    root = tmp_path_factory.mktemp( "repo" )
    git( root, "init", "-q" )
    for path in ( check.STATUS_PATH, check.RETRIEVAL_PATH ):
        ( root / path ).parent.mkdir( parents=True, exist_ok=True )
        shutil.copyfile( f"{cu.get_project_root()}/{path}", root / path )
    git( root, "add", "." )
    git( root, "commit", "-qm", "same" )
    same   = git( root, "rev-parse", "HEAD" )
    status = ( root / check.STATUS_PATH ).read_text()
    assert status.count( "MIN_SESSIONS    = 2" ) == 1
    ( root / check.STATUS_PATH ).write_text( status.replace( "MIN_SESSIONS    = 2", "MIN_SESSIONS    = 3" ) )
    git( root, "commit", "-qam", "changed" )
    return SimpleNamespace( root=str( root ), same=same, changed=git( root, "rev-parse", "HEAD" ) )


def build_archive( folder, cards, vectors=True ):
    """
    Write a small archive: two established principles and `cards` forecast rows.

    The stored evidence ids of the first card are the two principles retrieval keeps; the others are empty.
    """
    engine = create_engine( f"sqlite:///{folder}/archive.sqlite" )
    for model in scratch_db.TABLES: model.__table__.create( engine )
    with Session( engine ) as session:
        for n in ( 1, 2 ):
            session.add( PreferencePrinciple( id=uid( n ), owner_id=OWNER, kind="decision", dimension="d", statement=f"s{n}", scope="global",
                                              embedding=[ 1.0, n / 10.0 ] + [ 0.0 ] * 766, encoder_version=ENC, extractor_version=EXT ) )
            for note in ( 1, 2 ):
                session.add( PreferenceEvidence( id=uuid.uuid4(), principle_id=uid( n ), notification_id=uid( 100 + note ), field_key="f", relation="supports",
                                                 answered_at=ASK - timedelta( hours=1 ), extracted_at=ASK - timedelta( hours=1 ), extractor_version=EXT,
                                                 source="extractor", session_key=f"session-{note}" ) )
        for number in range( cards ):
            note = uid( 1000 + number )
            session.add( Notification( id=note, recipient_id=uuid.UUID( OWNER ), sender_id="claude.code@lupin.deepily.ai#aaaa1111", title=f"card {number}", message="m",
                                       type="custom", priority="low", response_type="yes_no", response_requested=True, created_at=ASK ) )
            session.add( PredictionArmForecast( notification_id=note, arm=check.ARM, predictor_version="v", input_cutoff=ASK + timedelta( seconds=number ),
                                                evidence_ids=[ str( uid( 1 ) ), str( uid( 2 ) ) ] if number == 0 else None, displayed=False ) )
        session.commit()
        cache = {}
        if vectors:
            for number in range( cards ):
                cache[ cache_key( card_text( episode_view( session, uid( 1000 + number ), limit=1 ) ), ENC ) ] = VECTOR
    engine.dispose()
    ( folder / "embeddings.json" ).write_text( json.dumps( cache ) )
    return str( folder )


def run_main( monkeypatch, repo, archive, base, *extra ):
    """Run main against the throwaway repository and return its exit code and its summary."""
    monkeypatch.setattr( check, "cu", SimpleNamespace( get_project_root=lambda: repo.root ) )
    lines = []
    code  = check.main( [ "--archive", archive, "--base", base, *extra ], out=lines.append )
    return code, json.loads( lines[ -1 ] ), lines[ :-1 ]


def test_the_same_code_on_both_sides_finds_no_difference( monkeypatch, tmp_path, repo ):
    """Every card compares equal, progress prints at 100, stored selections are counted."""
    archive = build_archive( tmp_path, 100 )
    code, summary, progress = run_main( monkeypatch, repo, archive, repo.same )
    assert code == 0
    assert ( summary[ "compared" ], summary[ "with_principles" ], summary[ "different_count" ] ) == ( 100, 100, 0 )
    assert summary[ "stored_selection_equal" ] == 1
    assert ( summary[ "principles" ], summary[ "evidence" ] ) == ( 2, 4 )
    assert set( summary[ "retrieve_ms" ] ) == { "old_median", "new_median", "old_mean", "new_mean" }
    assert progress == [ "[check] 100/100 cards, 0 differ" ]


def test_a_changed_rule_in_the_old_code_is_reported( monkeypatch, tmp_path, repo ):
    """Old code wanting three sessions to establish differs in all four comparisons."""
    archive = build_archive( tmp_path, 1 )
    code, summary, _ = run_main( monkeypatch, repo, archive, repo.changed )
    assert code == 1
    assert summary[ "different" ] == [ [ str( uid( 1000 ) ), [ "retrieval", "retrieval with applicability and caveats", "standings", "standings with both switches on" ] ] ]


def test_no_cached_vector_compares_nothing( monkeypatch, tmp_path, repo ):
    """A card with no cached vector is skipped and counted, and the run is not a pass."""
    archive = build_archive( tmp_path, 3, vectors=False )
    code, summary, _ = run_main( monkeypatch, repo, archive, repo.same )
    assert code == 2
    assert ( summary[ "cards" ], summary[ "compared" ], summary[ "without_vector" ] ) == ( 3, 0, 3 )
    assert summary[ "retrieve_ms" ] == {} and summary[ "derive_ms" ] == {}


def test_every_offset_and_limit_split_the_cards( monkeypatch, tmp_path, repo ):
    """Two offsets of every second card cover all five once; a limit cuts."""
    archive = build_archive( tmp_path, 5 )
    counts  = [ run_main( monkeypatch, repo, archive, repo.same, "--every", "2", "--offset", str( k ) )[ 1 ][ "cards" ] for k in ( 0, 1 ) ]
    assert counts == [ 3, 2 ]
    assert run_main( monkeypatch, repo, archive, repo.same, "--limit", "2" )[ 1 ][ "cards" ] == 2


def test_a_commit_without_the_file_is_refused( repo ):
    """An unknown commit stops the check rather than comparing nothing."""
    with pytest.raises( RuntimeError, match="git show" ): check.module_at( repo.root, "0" * 40, check.STATUS_PATH )
