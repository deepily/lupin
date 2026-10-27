"""
The pair labelling router and its page: progress, durable labels, blindness.

The packets come from the real exporter and the labels file is read back with the real reader.
The router is mounted on a small app with the auth dependency replaced.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.repo.labelling import items as it
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import pair_labels as pl
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers import pages
from cosa.rest.routers import pair_labelling as plr

URL = "/api/pair-labelling"


@pytest.fixture
def env( tmp_path, monkeypatch ):
    """Make a packets folder for two reviewers, an unread key folder, and a client."""
    items = [ it.make_item( it.SEMDUP_PAIR, f"pair-{n}", { "a": f"def a{n}(): pass", "b": f"def b{n}(): pass" } ) for n in range( 3 ) ]
    packets = tmp_path / "packets"
    pk.export_packets( items, [ "rick", "second" ], "seed", packets )
    ( tmp_path / "key" ).mkdir()
    monkeypatch.setenv( plr.DIR_VARIABLE, str( packets ) )
    app = FastAPI()
    app.include_router( plr.router )
    app.include_router( pages.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app ), packets


def ids_of( packets, reviewer="rick" ): return [ i[ "item_id" ] for i in pl.load_items( pk.packet_path( packets, reviewer ) ) ]


def test_state_starts_at_position_zero( env ):
    c, _ = env
    assert c.get( f"{URL}/state" ).json() == { "reviewer": "rick", "total": 3, "labelled": 0, "unsure": 0, "resume": 0 }


def test_item_sends_id_a_b_position_and_nothing_that_breaks_blindness( env ):
    c, packets = env
    body = c.get( f"{URL}/item", params={ "position": 1 } ).json()
    assert sorted( body ) == [ "a", "b", "item_id", "label", "labelled", "position", "total" ]
    assert body[ "item_id" ] == ids_of( packets )[ 1 ] and body[ "label" ] is None and body[ "total" ] == 3
    assert "type" not in body and "payload" not in body


def test_a_label_is_on_disk_before_the_post_returns_and_resume_moves_on( env ):
    c, packets = env
    first = ids_of( packets )[ 0 ]
    state = c.post( f"{URL}/label", json={ "item_id": first, "same_job": True } ).json()
    assert state == { "reviewer": "rick", "total": 3, "labelled": 1, "unsure": 0, "resume": 1 }
    assert pl.same_job_labels( packets / "labels-rick.jsonl" ) == { first: True }
    assert c.get( f"{URL}/item", params={ "position": 0 } ).json()[ "label" ] == { "same_job": True, "unsure": False, "note": "" }


def test_a_reload_resumes_at_the_first_unlabelled_pair_after_labels_were_written_out_of_order( env ):
    c, packets = env
    ids = ids_of( packets )
    for n in ( ids[ 0 ], ids[ 2 ] ): c.post( f"{URL}/label", json={ "item_id": n, "same_job": False } )
    assert c.get( f"{URL}/state" ).json()[ "resume" ] == 1


def test_unsure_is_stored_as_a_note_and_comes_back_as_a_flag_then_resume_revisits_it( env ):
    c, packets = env
    ids = ids_of( packets )
    c.post( f"{URL}/label", json={ "item_id": ids[ 0 ], "same_job": True, "unsure": True, "note": "hmm" } )
    for n in ids[ 1: ]: state = c.post( f"{URL}/label", json={ "item_id": n, "same_job": False } ).json()
    assert state[ "unsure" ] == 1 and state[ "resume" ] == 0
    assert pk.read_labels( packets / "labels-rick.jsonl" )[ 0 ][ "note" ] == "UNSURE: hmm"
    assert c.get( f"{URL}/item", params={ "position": 0 } ).json()[ "label" ] == { "same_job": True, "unsure": True, "note": "hmm" }
    assert c.post( f"{URL}/label", json={ "item_id": ids[ 0 ], "same_job": True } ).json()[ "resume" ] is None


def test_each_reviewer_has_their_own_labels_file( env ):
    c, packets = env
    c.post( f"{URL}/label", json={ "item_id": ids_of( packets, "second" )[ 0 ], "same_job": True, "reviewer": "second" } )
    assert ( packets / "labels-second.jsonl" ).exists() and not ( packets / "labels-rick.jsonl" ).exists()
    assert c.get( f"{URL}/state", params={ "reviewer": "second" } ).json()[ "labelled" ] == 1


def test_refusals( env ):
    c, packets = env
    assert c.get( f"{URL}/item", params={ "position": 3 } ).status_code == 404
    assert c.get( f"{URL}/item", params={ "position": -1 } ).status_code == 404
    assert c.get( f"{URL}/state", params={ "reviewer": "nobody" } ).status_code == 404
    assert c.get( f"{URL}/state", params={ "reviewer": "../key" } ).status_code == 422
    assert c.post( f"{URL}/label", json={ "item_id": "pair-nope", "same_job": True } ).status_code == 404
    assert c.post( f"{URL}/label", json={ "item_id": ids_of( packets )[ 0 ], "same_job": True, "note": "x" * 3000 } ).status_code == 422
    assert not ( packets / "labels-rick.jsonl" ).exists()


def test_a_packet_that_leaks_is_a_500_naming_the_error( env ):
    c, packets = env
    ( packets / "packet-rick.jsonl" ).write_text( json.dumps( { "item_id": "p", "type": "semdup_pair", "payload": { "a": "x", "b": "y", "verdict": "SAME" } } ) + "\n" )
    r = c.get( f"{URL}/state" )
    assert r.status_code == 500 and "PACKET_LEAK" in r.json()[ "detail" ]


def test_packets_dir_defaults_under_the_project_root_and_follows_the_variable( monkeypatch, tmp_path ):
    monkeypatch.delenv( plr.DIR_VARIABLE, raising=False )
    assert str( plr.packets_dir() ).endswith( plr.DEFAULT_DIR )
    monkeypatch.setenv( plr.DIR_VARIABLE, f" {tmp_path} " )
    assert plr.packets_dir() == tmp_path


def test_the_page_is_served_with_revalidation_and_is_blind( env ):
    c, _ = env
    r = c.get( "/app/pair-labelling" )
    assert r.status_code == 200 and r.headers[ "cache-control" ] == "no-cache"
    page = r.text
    assert "/api/pair-labelling" in page and "item.type" not in page and "/key" not in page and "verdict" not in page


def test_every_route_refuses_a_caller_with_no_credentials( env ):
    _, packets = env
    app = FastAPI()
    app.include_router( plr.router )
    bare = TestClient( app )
    first = ids_of( packets )[ 0 ]
    assert bare.get( f"{URL}/state" ).status_code == 401
    assert bare.get( f"{URL}/item", params={ "position": 0 } ).status_code == 401
    assert bare.post( f"{URL}/label", json={ "item_id": first, "same_job": True } ).status_code == 401
    assert not ( packets / "labels-rick.jsonl" ).exists()


def test_a_click_saves_and_stays_on_the_same_pair_and_only_the_buttons_move():
    """Run the page script under node with a fake DOM: a click must not move the page."""
    import pathlib, shutil, subprocess
    if shutil.which( "node" ) is None: pytest.skip( "node is not installed" )
    here = pathlib.Path( __file__ ).resolve()
    page = here.parents[ 2 ] / "lupin_app" / "static" / "html" / "pair-labelling.html"
    r = subprocess.run( [ "node", str( here.with_name( "pair_labelling_page_driver.js" ) ), str( page ) ], capture_output=True, text=True, timeout=60 )
    assert r.returncode == 0, r.stderr
    out = json.loads( r.stdout.strip().splitlines()[ -1 ] )
    assert out[ "start" ].startswith( "Pair 1 of 4" )
    assert out[ "after_yes" ][ "a" ] == "a0" and out[ "after_yes" ][ "progress" ].startswith( "Pair 1 of 4 · 1 labelled" )
    assert "Saved: Same job" in out[ "after_yes" ][ "status" ] and "chosen" in out[ "after_yes" ][ "yes" ]
    assert out[ "after_change" ][ "a" ] == "a0" and "Saved: Not the same job" in out[ "after_change" ][ "status" ]
    assert "chosen" in out[ "after_change" ][ "no" ] and "chosen" not in out[ "after_change" ][ "yes" ]
    assert out[ "after_change" ][ "progress" ].startswith( "Pair 1 of 4 · 1 labelled" )
    assert out[ "next" ] == "a1" and out[ "prev" ][ "a" ] == "a0" and "Saved: Not the same job" in out[ "prev" ][ "status" ]
    assert out[ "arrow_right" ] == "a1" and out[ "arrow_left" ] == "a0"
    assert "Saved: Same job" in out[ "after_yes" ][ "marker" ]
    assert out[ "goto" ] == { "a": "a2", "marker": "Not yet labelled" }
    assert out[ "goto_back" ][ "a" ] == "a0" and "Saved: Not the same job" in out[ "goto_back" ][ "marker" ] and out[ "goto_out" ] == "a0"
    assert out[ "bad_goto" ] == { "page": "a0", "fetched": 0 }
    assert out[ "typing" ] == { "moved": False, "fetched": 0 }
    assert out[ "resume" ] == "a1" and out[ "label_posts" ] == 2
