"""
Rick's offline page: the blind share of cards, the item list, and the one-file HTML.
"""
import json
import re

import pytest

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it
from cosa.repo.labelling import rick_page as rp


def card_item( item_id, stance="yes", options=None, recommendation=None, answer="yes", text="Question?" ):
    """Return an answer_meaning_card item."""
    return it.make_item( it.ANSWER_CARD, item_id, { "card_text": text, "options": options or [], "recommendation": recommendation, "answer": answer, "stance_class": stance } )


def packet_of( cards=40, fields=2 ):
    """
    Return a packet of cards; every third card holds `fields` items, the rest one.

    Item ids are card id + ":" + number, and refs carry the card id, as build_answer_card_sample writes them.
    """
    blind, refs = [], {}
    for c in range( cards ):
        for f in range( fields if c % 3 == 0 else 1 ):
            item = card_item( f"card-{c:03d}:{f}", options=[ "A", "B" ] if f else [], recommendation="A" if f else None, stance="none" if f else "yes" )
            blind.append( item )
            refs[ item[ "item_id" ] ] = { "notification_id": f"card-{c:03d}", "field_key": f"f{f}" }
    return { "name": "dev-sample", "blind": blind, "disputes": [], "refs": refs }


def code_of( fn, *args ):
    """Return the code of the LabellingError that fn raises."""
    with pytest.raises( er.LabellingError ) as e: fn( *args )
    return e.value.code


def test_every_kind_of_item_gets_only_its_own_relations():
    stance = card_item( "s:0" )
    choice = card_item( "c:0", stance="none", options=[ "A", "B" ], recommendation="A" )
    bare   = card_item( "n:0", stance="none", options=[ "A", "B" ] )
    open_  = card_item( "o:0", stance="none" )
    assert [ rp.kind_of( i ) for i in ( stance, choice, bare, open_ ) ] == [ "stance", "choice", "choice", "open" ]
    assert rp.relations_for( stance ) == [ "support", "dissent", "re_frame", "no_comment" ]
    assert rp.relations_for( choice ) == [ "agrees", "expands_recommendation", "expands_other_option", "chose_different_listed_option", "wrote_own_answer" ]
    assert rp.relations_for( bare ) == [ "chose_different_listed_option", "wrote_own_answer", "no_recommendation_on_card" ]
    assert rp.relations_for( open_ ) == [ "no_answer", "answers", "declines_or_defers", "re_frame" ]


def test_the_thirteen_relations_are_the_answer_labels_each_with_a_meaning():
    from cosa.repo.labelling import packets as pk
    shown = { l for labels in rp.RELATIONS.values() for l in labels }
    assert shown == set( pk.ANSWER_LABELS ) and set( rp.MEANINGS ) == set( pk.ANSWER_LABELS ) and len( pk.ANSWER_LABELS ) == 13
    assert all( m.strip() for m in rp.MEANINGS.values() )


def test_the_id_hash_is_the_sorted_ids_joined_by_newline_with_no_trailing_newline():
    import hashlib
    assert rp.ids_sha256( [ "b", "a" ] ) == hashlib.sha256( b"a\nb" ).hexdigest()
    assert rp.page_id( [ "b", "a" ] ) == hashlib.sha256( b"a\nb" ).hexdigest()[ :12 ]


def test_the_share_is_a_fifth_of_the_cards_with_one_field_each_and_is_repeatable():
    packet = packet_of( 40, 3 )
    one    = rp.draw_share( packet, "seed-1" )
    cards  = [ i.split( ":" )[ 0 ] for i in one[ "item_ids" ] ]
    assert one[ "cards_total" ] == 40 and len( one[ "card_ids" ] ) == 8 and len( one[ "item_ids" ] ) == 8
    assert sorted( cards ) == one[ "card_ids" ] and len( set( cards ) ) == 8
    assert one[ "item_ids_sha256" ] == rp.ids_sha256( one[ "item_ids" ] ) and one[ "seed" ] == "seed-1" and one[ "share" ] == 0.2
    shuffled = dict( packet, blind=list( reversed( packet[ "blind" ] ) ) )
    assert rp.draw_share( shuffled, "seed-1" ) == one
    assert rp.draw_share( packet, "seed-2" )[ "card_ids" ] != one[ "card_ids" ]


def test_a_drawn_multi_field_card_gives_a_field_the_seed_picks_and_not_always_the_first():
    packet  = packet_of( 40, 3 )
    picked  = set()
    for seed in ( "a", "b", "c", "d", "e", "f" ):
        share = rp.draw_share( packet, seed, share=0.9 )
        picked |= { i for i in share[ "item_ids" ] if i.endswith( ( ":1", ":2" ) ) }
    assert picked, "a draw of nearly every card must pick a later field of some multi-field card"


def test_a_packet_with_no_items_or_an_item_with_no_ref_is_refused():
    assert code_of( rp.draw_share, { "blind": [], "refs": {} }, "s" ) == er.BAD_ITEM
    packet = packet_of( 5, 1 )
    del packet[ "refs" ][ "card-001:0" ]
    assert code_of( rp.draw_share, packet, "s" ) == er.BAD_ITEM


def test_the_sections_keep_their_order_and_an_id_an_earlier_section_holds_is_dropped_from_a_later_one():
    kept, dropped = rp.merge_sections( { "first": [ "b", "a" ], "second": [ "c", "a", "d" ], "third": [ "a" ] } )
    assert kept == { "first": [ "a", "b" ], "second": [ "c", "d" ], "third": [] } and dropped == [ "a", "a" ]
    assert list( kept ) == [ "first", "second", "third" ]
    assert code_of( rp.merge_sections, { "s": [ "a", "a" ] } ) == er.BAD_ITEM
    assert code_of( rp.merge_sections, { " ": [ "a" ] } ) == er.BAD_ITEM


def test_the_page_items_follow_section_then_sorted_order_and_carry_their_relations_and_nothing_else():
    packet = packet_of( 6, 2 )
    out    = rp.page_items( packet, { "blind share": [ "card-003:1", "card-001:0" ], "reader disagreements": [ "card-000:0" ] } )
    assert [ ( o[ "item_id" ], o[ "section" ] ) for o in out ] == [ ( "card-003:1", "blind share" ), ( "card-001:0", "blind share" ), ( "card-000:0", "reader disagreements" ) ]
    assert set( out[ 0 ] ) == { "item_id", "section", "card_text", "options", "recommendation", "answer", "stance_class", "relations" }
    assert [ r[ "label" ] for r in out[ 0 ][ "relations" ] ] == rp.relations_for( next( i for i in packet[ "blind" ] if i[ "item_id" ] == "card-003:1" ) ) and out[ 0 ][ "recommendation" ] == "A"
    assert out[ 1 ][ "relations" ][ 0 ] == { "label": "support", "meaning": rp.MEANINGS[ "support" ] }


def test_the_page_takes_disputed_items_too_and_refuses_unknown_or_no_ids_and_a_leak():
    packet = packet_of( 3, 1 )
    packet[ "disputes" ] = [ card_item( "card-900:0" ) ]
    assert [ o[ "item_id" ] for o in rp.page_items( packet, { "s": [ "card-900:0" ] } ) ] == [ "card-900:0" ]
    assert code_of( rp.page_items, packet, {} ) == er.BAD_ITEM
    assert code_of( rp.page_items, packet, { "s": [] } ) == er.BAD_ITEM
    assert code_of( rp.page_items, packet, { "s": [ "nope" ] } ) == er.BAD_ITEM
    packet[ "blind" ][ 0 ][ "payload" ][ "forecast" ] = "yes, 0.9"
    assert code_of( rp.page_items, packet, { "s": [ "card-000:0" ] } ) == er.PACKET_LEAK


def test_read_ids_takes_a_json_list_or_words_and_a_json_object_is_read_as_words(tmp_path):
    ( tmp_path / "a.json" ).write_text( '["x:0", "y:1"]', encoding="utf-8" )
    ( tmp_path / "b.txt" ).write_text( "x:0\ny:1\n", encoding="utf-8" )
    ( tmp_path / "c.json" ).write_text( '{"k": 1}', encoding="utf-8" )
    assert rp.read_ids( tmp_path / "a.json" ) == [ "x:0", "y:1" ] == rp.read_ids( tmp_path / "b.txt" )
    assert rp.read_ids( tmp_path / "c.json" ) == [ '{"k":', "1}" ]


def test_embedded_json_is_ascii_and_cannot_close_a_script_element():
    text = rp.embed_json( { "a": "</script><b>&é" } )
    assert "<" not in text and ">" not in text and "&" not in text and text.isascii()
    assert json.loads( text ) == { "a": "</script><b>&é" }


def test_the_rendered_page_holds_its_items_and_reaches_for_nothing_outside():
    packet = packet_of( 6, 2 )
    items  = rp.page_items( packet, { "s": [ i[ "item_id" ] for i in packet[ "blind" ] ] } )
    html   = rp.render_page( items, "A <b>title</b> & more" )
    for token in ( "__TITLE__", "__PAGE_ID__", "__ITEMS_JSON__" ): assert token not in html
    assert "<title>A &lt;b&gt;title&lt;/b&gt; &amp; more</title>" in html
    assert f'var PAGE_ID  = "{rp.page_id( [ i[ "item_id" ] for i in items ] )}"' in html
    data = re.search( r'<script type="application/json" id="data">(.*?)</script>', html, re.S ).group( 1 )
    assert json.loads( data ) == items
    assert not re.search( r"<script[^>]*\ssrc=|<link\b|@import|url\(|https?://|fetch\(|XMLHttpRequest|WebSocket", html )


def test_the_page_script_keeps_answers_in_local_storage_and_exports_the_five_fields():
    html = rp.render_page( rp.page_items( packet_of( 3, 1 ), { "s": [ "card-000:0" ] } ), "t" )
    assert "localStorage" in html and "item_id: i.item_id, relation: e.relation, note: e.note, seconds: e.seconds, ts: e.ts" in html


def test_a_blank_title_or_no_items_is_refused():
    items = rp.page_items( packet_of( 3, 1 ), { "s": [ "card-000:0" ] } )
    assert code_of( rp.render_page, items, "  " ) == er.BAD_ITEM
    assert code_of( rp.render_page, [], "title" ) == er.BAD_ITEM


def write_packet( tmp_path, packet ):
    """Write the packet and return its path."""
    path = tmp_path / "packet.json"
    path.write_text( json.dumps( packet ), encoding="utf-8" )
    return path


def test_main_draws_writes_the_page_the_ids_and_the_sections_and_prints_the_receipt( tmp_path, capsys ):
    packet = packet_of( 40, 3 )
    path   = write_packet( tmp_path, packet )
    out    = tmp_path / "page.html"
    assert rp.main( [ "--packet", str( path ), "--draw", "seed-1", "--out", str( out ), "--title", "T" ] ) == 0
    receipt = json.loads( capsys.readouterr().out )
    ids     = out.with_name( "page.html.ids.txt" ).read_text( encoding="utf-8" ).split()
    drawn   = rp.draw_share( packet, "seed-1" )[ "item_ids" ]
    assert ids == receipt[ "item_ids" ] == drawn and receipt[ "items" ] == 8 and receipt[ "sections" ] == { "blind share": 8 } and receipt[ "dropped_as_already_listed" ] == []
    assert json.loads( out.with_name( "page.html.sections.json" ).read_text( encoding="utf-8" ) ) == { "blind share": drawn }
    assert receipt[ "page_id" ] == rp.page_id( ids ) and len( receipt[ "page_sha256" ] ) == 64
    assert f'var PAGE_ID  = "{receipt[ "page_id" ]}"' in out.read_text( encoding="utf-8" )


def test_main_adds_the_disputes_after_the_draw_and_drops_the_ones_already_drawn( tmp_path, capsys ):
    packet  = packet_of( 40, 3 )
    path    = write_packet( tmp_path, packet )
    drawn   = rp.draw_share( packet, "seed-1" )[ "item_ids" ]
    spare   = [ i[ "item_id" ] for i in packet[ "blind" ] if i[ "item_id" ] not in drawn ][ :3 ]
    ids     = tmp_path / "disputes.json"
    ids.write_text( json.dumps( [ drawn[ 0 ], *spare ] ), encoding="utf-8" )
    out     = tmp_path / "page.html"
    assert rp.main( [ "--packet", str( path ), "--draw", "seed-1", "--section", f"reader disagreements={ids}", "--out", str( out ) ] ) == 0
    receipt = json.loads( capsys.readouterr().out )
    assert receipt[ "items" ] == 11 and receipt[ "sections" ] == { "blind share": 8, "reader disagreements": 3 } and receipt[ "dropped_as_already_listed" ] == [ drawn[ 0 ] ]
    html = out.read_text( encoding="utf-8" )
    data = json.loads( re.search( r'<script type="application/json" id="data">(.*?)</script>', html, re.S ).group( 1 ) )
    assert [ d[ "section" ] for d in data ] == [ "blind share" ] * 8 + [ "reader disagreements" ] * 3 and [ d[ "item_id" ] for d in data[ 8: ] ] == sorted( spare )


def test_main_never_overwrites_a_page_and_the_receipt_only_run_writes_nothing( tmp_path, capsys ):
    path = write_packet( tmp_path, packet_of( 40, 3 ) )
    out  = tmp_path / "page.html"
    assert rp.main( [ "--packet", str( path ), "--draw", "s", "--out", str( out ), "--receipt-only" ] ) == 0
    assert not out.exists() and "page_sha256" not in json.loads( capsys.readouterr().out )
    assert rp.main( [ "--packet", str( path ), "--draw", "s", "--out", str( out ) ] ) == 0
    before = out.read_text( encoding="utf-8" )
    assert rp.main( [ "--packet", str( path ), "--draw", "other", "--out", str( out ) ] ) == 2
    assert "refused" in capsys.readouterr().err and out.read_text( encoding="utf-8" ) == before


def test_main_builds_a_page_from_sections_alone_such_as_a_later_dispute_list( tmp_path, capsys ):
    path = write_packet( tmp_path, packet_of( 6, 1 ) )
    ids  = tmp_path / "ids.txt"
    ids.write_text( "card-004:0\ncard-001:0\n", encoding="utf-8" )
    out  = tmp_path / "disputes.html"
    assert rp.main( [ "--packet", str( path ), "--section", f"disputes={ids}", "--out", str( out ) ] ) == 0
    receipt = json.loads( capsys.readouterr().out )
    assert receipt[ "items" ] == 2 and "item_ids" not in receipt and out.with_name( "disputes.html.ids.txt" ).read_text( encoding="utf-8" ) == "card-001:0\ncard-004:0\n"


@pytest.mark.parametrize( "ids_text", [ "", "nope\n", "card-001:0\ncard-001:0\n" ] )
def test_main_refuses_bad_ids_and_an_unreadable_packet_and_writes_nothing( tmp_path, capsys, ids_text ):
    path = write_packet( tmp_path, packet_of( 6, 1 ) )
    ids  = tmp_path / "ids.txt"
    ids.write_text( ids_text, encoding="utf-8" )
    out  = tmp_path / "p.html"
    assert rp.main( [ "--packet", str( path ), "--section", f"s={ids}", "--out", str( out ) ] ) == 2
    assert not out.exists() and "cannot build the page" in capsys.readouterr().err
    assert rp.main( [ "--packet", str( tmp_path / "absent.json" ), "--draw", "s", "--out", str( out ) ] ) == 2
    assert not out.exists()
