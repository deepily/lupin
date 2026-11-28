"""
Rick's offline page: the blind share of cards, the item list, and the one-file HTML.
"""
import json
import re

import pytest

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it
from cosa.repo.labelling import rick_page as rp
import cosa.utils.util as cu


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


def types_of( packet, kind="yes_no" ):
    """Return a card-types dict that gives every item of the packet the one kind."""
    return { i[ "item_id" ]: kind for i in packet[ "blind" ] + packet[ "disputes" ] }


def page_of( packet, ids ):
    """Return the page items of one section of ids, every item typed yes_no."""
    return rp.page_items( packet, { "s": ids }, types_of( packet ) )


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
    out    = rp.page_items( packet, { "blind share": [ "card-003:1", "card-001:0" ], "reader disagreements": [ "card-000:0" ] }, types_of( packet ) )
    assert [ ( o[ "item_id" ], o[ "section" ] ) for o in out ] == [ ( "card-003:1", "blind share" ), ( "card-001:0", "blind share" ), ( "card-000:0", "reader disagreements" ) ]
    assert set( out[ 0 ] ) == { "item_id", "section", "card_type", "card_text", "options", "recommendation", "answer", "stance_class", "question", "relations" }
    assert [ r[ "label" ] for r in out[ 0 ][ "relations" ] ] == rp.relations_for( next( i for i in packet[ "blind" ] if i[ "item_id" ] == "card-003:1" ) ) and out[ 0 ][ "recommendation" ] == "A"
    assert out[ 1 ][ "relations" ][ 0 ] == { "label": "support", "meaning": rp.MEANINGS[ "support" ] }


def test_the_page_takes_disputed_items_too_and_refuses_unknown_or_no_ids_and_a_leak():
    packet = packet_of( 3, 1 )
    packet[ "disputes" ] = [ card_item( "card-900:0" ) ]
    assert [ o[ "item_id" ] for o in rp.page_items( packet, { "s": [ "card-900:0" ] }, types_of( packet ) ) ] == [ "card-900:0" ]
    assert code_of( rp.page_items, packet, {}, {} ) == er.BAD_ITEM
    assert code_of( rp.page_items, packet, { "s": [] }, {} ) == er.BAD_ITEM
    assert code_of( rp.page_items, packet, { "s": [ "nope" ] }, {} ) == er.BAD_ITEM
    packet[ "blind" ][ 0 ][ "payload" ][ "forecast" ] = "yes, 0.9"
    assert code_of( rp.page_items, packet, { "s": [ "card-000:0" ] }, types_of( packet ) ) == er.PACKET_LEAK


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
    items  = rp.page_items( packet, { "s": [ i[ "item_id" ] for i in packet[ "blind" ] ] }, types_of( packet ) )
    html   = rp.render_page( items, "A <b>title</b> & more" )
    for token in ( "__TITLE__", "__PAGE_ID__", "__ITEMS_JSON__", "__TYPE_ORDER_JSON__" ): assert token not in html
    assert "<title>A &lt;b&gt;title&lt;/b&gt; &amp; more</title>" in html
    assert f'var PAGE_ID  = "{rp.page_id( [ i[ "item_id" ] for i in items ] )}"' in html
    data = re.search( r'<script type="application/json" id="data">(.*?)</script>', html, re.S ).group( 1 )
    assert json.loads( data ) == items
    assert not re.search( r"<script[^>]*\ssrc=|<link\b|@import|url\(|https?://|fetch\(|XMLHttpRequest|WebSocket", html )


def test_the_page_script_keeps_answers_in_local_storage_and_exports_the_five_fields():
    html = rp.render_page( page_of( packet_of( 3, 1 ), [ "card-000:0" ] ), "t" )
    assert "localStorage" in html and "item_id: i.item_id, relation: e.relation, note: e.note, seconds: e.seconds, ts: e.ts" in html


def test_an_item_with_no_id_fails_loudly_instead_of_naming_a_page():
    with pytest.raises( KeyError ):
        rp.render_page( [ { "card_type": "Yes / No / Neither" } ], "t" )


def test_a_blank_title_or_no_items_is_refused():
    items = page_of( packet_of( 3, 1 ), [ "card-000:0" ] )
    assert code_of( rp.render_page, items, "  " ) == er.BAD_ITEM
    assert code_of( rp.render_page, [], "title" ) == er.BAD_ITEM


def write_packet( tmp_path, packet ):
    """Write the packet and, beside it, its card types file, and return the packet's path."""
    path = tmp_path / "packet.json"
    path.write_text( json.dumps( packet ), encoding="utf-8" )
    ( tmp_path / "types.json" ).write_text( json.dumps( types_of( packet ) ), encoding="utf-8" )
    return path


def flags( tmp_path ):
    """Return the --card-types flag pair for the file write_packet wrote."""
    return [ "--card-types", str( tmp_path / "types.json" ) ]


def test_main_draws_writes_the_page_the_ids_and_the_sections_and_prints_the_receipt( tmp_path, capsys ):
    packet = packet_of( 40, 3 )
    path   = write_packet( tmp_path, packet )
    out    = tmp_path / "page.html"
    assert rp.main( flags( tmp_path ) + [ "--packet", str( path ), "--draw", "seed-1", "--out", str( out ), "--title", "T" ] ) == 0
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
    assert rp.main( flags( tmp_path ) + [ "--packet", str( path ), "--draw", "seed-1", "--section", f"reader disagreements={ids}", "--out", str( out ) ] ) == 0
    receipt = json.loads( capsys.readouterr().out )
    assert receipt[ "items" ] == 11 and receipt[ "sections" ] == { "blind share": 8, "reader disagreements": 3 } and receipt[ "dropped_as_already_listed" ] == [ drawn[ 0 ] ]
    html = out.read_text( encoding="utf-8" )
    data = json.loads( re.search( r'<script type="application/json" id="data">(.*?)</script>', html, re.S ).group( 1 ) )
    assert [ d[ "section" ] for d in data ] == [ "blind share" ] * 8 + [ "reader disagreements" ] * 3 and [ d[ "item_id" ] for d in data[ 8: ] ] == sorted( spare )


def test_main_never_overwrites_a_page_and_the_receipt_only_run_writes_nothing( tmp_path, capsys ):
    path = write_packet( tmp_path, packet_of( 40, 3 ) )
    out  = tmp_path / "page.html"
    assert rp.main( flags( tmp_path ) + [ "--packet", str( path ), "--draw", "s", "--out", str( out ), "--receipt-only" ] ) == 0
    assert not out.exists() and "page_sha256" not in json.loads( capsys.readouterr().out )
    assert rp.main( flags( tmp_path ) + [ "--packet", str( path ), "--draw", "s", "--out", str( out ) ] ) == 0
    before = out.read_text( encoding="utf-8" )
    assert rp.main( flags( tmp_path ) + [ "--packet", str( path ), "--draw", "other", "--out", str( out ) ] ) == 2
    assert "refused" in capsys.readouterr().err and out.read_text( encoding="utf-8" ) == before


def test_main_builds_a_page_from_sections_alone_such_as_a_later_dispute_list( tmp_path, capsys ):
    path = write_packet( tmp_path, packet_of( 6, 1 ) )
    ids  = tmp_path / "ids.txt"
    ids.write_text( "card-004:0\ncard-001:0\n", encoding="utf-8" )
    out  = tmp_path / "disputes.html"
    assert rp.main( flags( tmp_path ) + [ "--packet", str( path ), "--section", f"disputes={ids}", "--out", str( out ) ] ) == 0
    receipt = json.loads( capsys.readouterr().out )
    assert receipt[ "items" ] == 2 and "item_ids" not in receipt and out.with_name( "disputes.html.ids.txt" ).read_text( encoding="utf-8" ) == "card-001:0\ncard-004:0\n"


@pytest.mark.parametrize( "ids_text", [ "", "nope\n", "card-001:0\ncard-001:0\n" ] )
def test_main_refuses_bad_ids_and_an_unreadable_packet_and_writes_nothing( tmp_path, capsys, ids_text ):
    path = write_packet( tmp_path, packet_of( 6, 1 ) )
    ids  = tmp_path / "ids.txt"
    ids.write_text( ids_text, encoding="utf-8" )
    out  = tmp_path / "p.html"
    assert rp.main( flags( tmp_path ) + [ "--packet", str( path ), "--section", f"s={ids}", "--out", str( out ) ] ) == 2
    assert not out.exists() and "cannot build the page" in capsys.readouterr().err
    assert rp.main( flags( tmp_path ) + [ "--packet", str( tmp_path / "absent.json" ), "--draw", "s", "--out", str( out ) ] ) == 2
    assert not out.exists()


def test_every_item_carries_the_label_rick_reads_for_its_card_type():
    packet = packet_of( 4, 1 )
    types  = dict( zip( [ i[ "item_id" ] for i in packet[ "blind" ] ], rp.CARD_TYPE_LABELS ) )
    out    = rp.page_items( packet, { "s": sorted( types ) }, types )
    assert [ o[ "card_type" ] for o in out ] == [ "Yes / No / Neither", "Multiple choice", "Open-ended", "Batch (open-ended)" ]
    assert list( rp.CARD_TYPE_LABELS.values() ) == [ "Yes / No / Neither", "Multiple choice", "Open-ended", "Batch (open-ended)" ]


@pytest.mark.parametrize( "bad", [ None, "", "essay" ] )
def test_an_item_with_no_card_type_or_an_unknown_one_fails_loudly_and_never_shows_blank( bad ):
    packet = packet_of( 3, 1 )
    types  = types_of( packet )
    del types[ "card-001:0" ]
    assert code_of( rp.page_items, packet, { "s": [ "card-000:0", "card-001:0" ] }, types ) == er.BAD_ITEM
    types[ "card-001:0" ] = bad
    assert code_of( rp.page_items, packet, { "s": [ "card-001:0" ] }, types ) == er.BAD_ITEM


def test_the_page_id_depends_on_the_item_ids_only_so_a_card_type_never_moves_it():
    packet = packet_of( 6, 1 )
    ids    = [ i[ "item_id" ] for i in packet[ "blind" ] ]
    ones   = rp.page_items( packet, { "s": ids }, types_of( packet, "yes_no" ) )
    twos   = rp.page_items( packet, { "s": ids }, types_of( packet, "open_ended" ) )
    assert re.search( r'PAGE_ID  = "(\w+)"', rp.render_page( ones, "t" ) ).group( 1 ) == re.search( r'PAGE_ID  = "(\w+)"', rp.render_page( twos, "t" ) ).group( 1 ) == rp.page_id( ids )


def test_main_embeds_the_card_types_and_refuses_a_missing_or_short_or_odd_types_file( tmp_path, capsys ):
    packet = packet_of( 6, 1 )
    path   = write_packet( tmp_path, packet )
    out    = tmp_path / "p.html"
    ids    = tmp_path / "ids.txt"
    ids.write_text( "card-001:0 card-002:0", encoding="utf-8" )
    assert rp.main( flags( tmp_path ) + [ "--packet", str( path ), "--section", f"s={ids}", "--out", str( out ) ] ) == 0
    assert out.read_text( encoding="utf-8" ).count( "Yes / No / Neither" ) >= 2
    for body in ( None, "{}", "[]", "not json" ):
        out2 = tmp_path / f"p{body}.html"
        if body is None: bad = [ "--card-types", str( tmp_path / "absent.json" ) ]
        else:
            ( tmp_path / "bad.json" ).write_text( body, encoding="utf-8" )
            bad = [ "--card-types", str( tmp_path / "bad.json" ) ]
        assert rp.main( bad + [ "--packet", str( path ), "--section", f"s={ids}", "--out", str( out2 ) ] ) == 2
        assert not out2.exists() and "cannot build the page" in capsys.readouterr().err


def batch_packet():
    """
    Return a packet shaped like a real batch card: card A asks four questions and card B one.

    Each item's card text is the card's shared text plus its own question, as build_answer_card_sample writes it.
    """
    head    = "Missing arguments\nI have 4 questions for you. Question 1 of 4: budget? Question 2 of 4: languages?\n**Still needed**: budget, languages"
    fields  = [ ( "budget", "Would you like a budget limit?", "no limit" ), ( "languages", "What languages for the podcast?", "en" ),
                ( "audience", "Who is the target audience?", "academic" ), ( "audience_context", "Any context about the audience?", "none" ) ]
    blind, refs = [], {}
    for n, ( key, prompt, answer ) in enumerate( fields ):
        item = card_item( f"card-A:{n}", stance="none", answer=answer, text=f"{head}\n{prompt}" )
        blind.append( item )
        refs[ item[ "item_id" ] ] = { "notification_id": "card-A", "field_key": key }
    single = card_item( "card-B:0", stance="none", answer="sure", text="One question?" )
    blind.append( single )
    refs[ "card-B:0" ] = { "notification_id": "card-B", "field_key": "answer" }
    return { "name": "batch", "blind": blind, "disputes": [], "refs": refs }


def test_an_item_of_a_multi_question_card_names_its_own_question_and_a_single_card_names_none():
    packet = batch_packet()
    out    = { o[ "item_id" ]: o for o in rp.page_items( packet, { "s": [ "card-A:1", "card-A:3", "card-B:0" ] }, types_of( packet, "open_ended_batch" ) ) }
    assert out[ "card-A:1" ][ "question" ] == { "header": "languages", "prompt": "What languages for the podcast?", "answered": 4 }
    assert out[ "card-A:3" ][ "question" ] == { "header": "audience_context", "prompt": "Any context about the audience?", "answered": 4 }
    assert out[ "card-A:1" ][ "answer" ] == "en"
    assert out[ "card-B:0" ][ "question" ] is None


def test_the_prompt_is_cut_at_a_line_start_and_none_when_nothing_follows_the_shared_text():
    packet = batch_packet()
    for i in packet[ "blind" ][ :2 ]: i[ "payload" ][ "card_text" ] = "Shared\nWhat is x?" if i[ "item_id" ].endswith( "0" ) else "Shared\nWhat is y?"
    q = rp.questions_of( { **packet, "blind": packet[ "blind" ][ :2 ] } )
    assert q[ "card-A:0" ][ "prompt" ] == "What is x?" and q[ "card-A:1" ][ "prompt" ] == "What is y?"
    same = packet_of( 3, 2 )
    assert rp.questions_of( same )[ "card-000:1" ] == { "header": "f1", "prompt": "Question?", "answered": 2 }
    assert "card-001:0" not in rp.questions_of( same )
    for i in same[ "blind" ][ :2 ]: i[ "payload" ][ "card_text" ] = "Shared\n"
    assert rp.questions_of( same )[ "card-000:0" ][ "prompt" ] is None


def test_an_item_with_no_ref_is_left_out_of_the_question_map():
    packet = batch_packet()
    del packet[ "refs" ][ "card-A:0" ]
    q = rp.questions_of( packet )
    assert "card-A:0" not in q and q[ "card-A:1" ][ "answered" ] == 3


def test_naming_the_question_never_moves_the_page_id_so_saved_answers_carry_over():
    packet = batch_packet()
    ids    = [ "card-A:1", "card-B:0" ]
    html   = rp.render_page( rp.page_items( packet, { "s": ids }, types_of( packet, "open_ended_batch" ) ), "t" )
    assert re.search( r'PAGE_ID  = "(\w+)"', html ).group( 1 ) == rp.page_id( ids )


def test_the_page_shows_the_question_box_only_for_an_item_that_names_one():
    html = rp.render_page( page_of( batch_packet(), [ "card-A:1" ] ), "t" )
    assert 'id="questionbox"' in html and 'id="question"' in html


def drive( page ):
    """Run rick_page_question_driver.js on a page file under node and return what it reports."""
    import shutil, subprocess
    if shutil.which( "node" ) is None: pytest.skip( "node is not installed" )
    r = subprocess.run( [ "node", cu.get_project_root() + "/src/tests/unit/rick_page_question_driver.js", str( page ) ], capture_output=True, text=True, timeout=60 )
    assert r.returncode == 0, r.stderr
    return json.loads( r.stdout.strip().splitlines()[ -1 ] )


def test_the_page_script_shows_the_box_with_the_question_for_a_multi_question_item_and_hides_it_otherwise( tmp_path ):
    """Run the page script under node, so the box is judged by what show() does, not by the text."""
    packet = batch_packet()
    page   = tmp_path / "p.html"
    page.write_text( rp.render_page( rp.page_items( packet, { "s": [ "card-A:1", "card-B:0" ] }, types_of( packet, "open_ended_batch" ) ), "t" ), encoding="utf-8" )
    shown  = { o[ "item_id" ]: o for o in drive( page )[ "boxes" ] }
    assert len( shown ) == 2
    assert shown[ "card-A:1" ][ "display" ] == "block"
    assert shown[ "card-A:1" ][ "text" ].startswith( "languages: What languages for the podcast?\n(4 of this card's questions were answered." )
    assert shown[ "card-B:0" ][ "display" ] == "none" and shown[ "card-B:0" ][ "text" ] == ""


def test_the_order_button_groups_like_card_types_together_keeping_the_drawn_order_inside_each( tmp_path ):
    """Next walks the drawn order until the button is clicked, then one card type at a time."""
    packet = packet_of( 6, 1 )
    kinds  = [ "open_ended_batch", "yes_no", "open_ended_batch", "multiple_choice", "yes_no", "open_ended" ]
    types  = { f"card-{c:03d}:0": k for c, k in enumerate( kinds ) }
    ids    = sorted( types )
    page   = tmp_path / "p.html"
    page.write_text( rp.render_page( rp.page_items( packet, { "s": ids }, types ), "t" ), encoding="utf-8" )
    out    = drive( page )
    assert out[ "drawn" ][ "label" ] == "Order: as drawn" and out[ "drawn" ][ "ids" ] == ids
    assert out[ "grouped" ][ "label" ] == "Order: by card type"
    assert out[ "grouped" ][ "ids" ] == [ "card-001:0", "card-004:0", "card-003:0", "card-005:0", "card-000:0", "card-002:0" ]
    assert out[ "grouped" ][ "badges" ][ :2 ] == [ "Yes / No / Neither \u00b7 0 of 2 done" ] * 2
    assert out[ "grouped" ][ "badges" ][ -1 ] == "Batch (open-ended) \u00b7 0 of 2 done"
    assert out[ "next_open" ] == "card-004:0" and out[ "grouped_saved" ] is True


def test_the_grouped_view_orders_card_types_as_the_label_table_does():
    html = rp.render_page( page_of( packet_of( 3, 1 ), [ "card-000:0" ] ), "t" )
    assert "var TYPES    = " + rp.embed_json( list( rp.CARD_TYPE_LABELS.values() ) ) + ";" in html


@pytest.mark.parametrize( "token", [ "__TYPE_ORDER_JSON__", "__PAGE_ID__", "__TITLE__" ] )
def test_a_card_that_quotes_a_placeholder_reaches_the_page_unchanged( token ):
    packet = packet_of( 3, 1 )
    packet[ "blind" ][ 0 ][ "payload" ][ "card_text" ] = f"Should the page fill {token} before the items?"
    items  = page_of( packet, [ "card-000:0" ] )
    html   = rp.render_page( items, "t" )
    data   = re.search( r'<script type="application/json" id="data">(.*?)</script>', html, re.S ).group( 1 )
    assert json.loads( data ) == items and json.loads( data )[ 0 ][ "card_text" ] == f"Should the page fill {token} before the items?"
