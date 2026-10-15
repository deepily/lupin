"""
The wiki page list: pages ranked against the need, pins in id order, an id listed once.
"""
import random

from cosa.repo.symindex.candidates.wiki_list import wiki_ranked_ids

PAGES = [
    { "slug": "feeds",   "text": "Fetch and parse RSS and Atom feeds",        "pins": [ "cosa.feeds.parse_feed", "cosa.feeds.fetch" ] },
    { "slug": "queues",  "text": "The job queue and its consumer",            "pins": [ "cosa.rest.queue.push", "cosa.feeds.fetch" ] },
    { "slug": "voice",   "text": "Voice notifications and speech",            "pins": [ "cosa.voice.notify" ] },
]


def test_pages_are_ranked_by_the_need_and_their_pins_follow_in_id_order():
    assert wiki_ranked_ids( "parse an RSS feed", PAGES ) == [ "cosa.feeds.fetch", "cosa.feeds.parse_feed" ]


def test_an_id_already_listed_under_a_better_page_is_not_listed_again():
    got = wiki_ranked_ids( "job queue consumer feeds", PAGES )                       # the queue page matches three words, the feeds page one
    assert got.count( "cosa.feeds.fetch" ) == 1 and got == [ "cosa.feeds.fetch", "cosa.rest.queue.push", "cosa.feeds.parse_feed" ]


def test_a_page_that_shares_no_word_with_the_need_contributes_nothing():
    assert wiki_ranked_ids( "speech", PAGES ) == [ "cosa.voice.notify" ]
    assert wiki_ranked_ids( "quantum chromodynamics", PAGES ) == []


def test_no_pages_give_an_empty_list():
    assert wiki_ranked_ids( "anything", [] ) == []


def test_a_tie_between_pages_breaks_on_the_slug_and_the_page_order_does_not_matter():
    a = { "slug": "b-page", "text": "shared words here", "pins": [ "x.two" ] }
    b = { "slug": "a-page", "text": "shared words here", "pins": [ "x.one" ] }
    assert wiki_ranked_ids( "shared words", [ a, b ] ) == [ "x.one", "x.two" ]
    assert wiki_ranked_ids( "shared words", [ b, a ] ) == [ "x.one", "x.two" ]


def test_the_list_is_the_same_for_every_order_of_the_input():
    rng = random.Random( 3 )
    want = wiki_ranked_ids( "parse feeds queue notifications", PAGES )
    for _ in range( 20 ):
        pages = list( PAGES )
        rng.shuffle( pages )
        assert wiki_ranked_ids( "parse feeds queue notifications", pages ) == want
