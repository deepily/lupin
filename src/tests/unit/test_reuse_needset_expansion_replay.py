"""
Need expansion, run on fakes with no model call.

The draft takes the model and the search as arguments, so every part is checked here.
"""
import json

from lupin_mcp.reuse_needset import expansion_replay as ex

FUSION  = { "k": 60, "depth": 512, "head": 5 }
GOOD    = json.dumps( { "paraphrases": [ "one", "two", "three" ], "identifiers": [ "alpha", "beta" ] } )


class Ledger:
    """A dict standing in for the saved-answer ledger."""
    def __init__( self ): self.rows = { }
    def get( self, key ): return self.rows.get( key )
    def put( self, key, value ): self.rows[ key ] = value


def test_the_prompt_holds_the_need_sentence_and_names_what_is_wanted():
    text = ex.expansion_prompt( "a function that trims a string" )
    assert "Description: a function that trims a string" in text and "three different wordings" in text and "five words" in text


def test_parse_expansion_reads_the_reply_inside_extra_text_and_strips_each_word():
    assert ex.parse_expansion( "Here: " + GOOD + " done" ) == { "paraphrases": [ "one", "two", "three" ], "identifiers": [ "alpha", "beta" ] }
    assert ex.parse_expansion( '{"paraphrases": [" a ", "b", "c"], "identifiers": [" x "]}' ) == { "paraphrases": [ "a", "b", "c" ], "identifiers": [ "x" ] }


def test_parse_expansion_refuses_every_wrong_shape():
    bad = [ "no json", "{broken", '{"paraphrases": ["a","b","c"]}', '{"paraphrases": "abc", "identifiers": ["x"]}', '{"paraphrases": ["a","b"], "identifiers": ["x"]}',
            '{"paraphrases": ["a","b","c"], "identifiers": []}', '{"paraphrases": ["a","b","c"], "identifiers": ["1","2","3","4","5","6"]}',
            '{"paraphrases": ["a","b",""], "identifiers": ["x"]}', '{"paraphrases": ["a","b",3], "identifiers": ["x"]}', "[1]" ]
    assert [ ex.parse_expansion( r ) for r in bad ] == [ None ] * len( bad )


def test_queries_for_lists_the_need_then_the_paraphrases_then_the_joined_identifiers():
    assert ex.queries_for( "need", { "paraphrases": [ "p1", "p2", "p3" ], "identifiers": [ "a", "b" ] } ) == [ "need", "p1", "p2", "p3", "a b" ]


def test_expand_need_asks_once_and_saves_the_reply_even_when_it_is_unreadable():
    ledger, asked = Ledger(), [ ]
    def ask( system, prompt ): asked.append( ( system, prompt ) ); return GOOD
    assert ex.expand_need( "n", ask, ledger, "m" )[ "identifiers" ] == [ "alpha", "beta" ]
    assert ex.expand_need( "n", ask, ledger, "m" )[ "identifiers" ] == [ "alpha", "beta" ] and len( asked ) == 1 and asked[ 0 ][ 0 ] == ex.SYSTEM
    ledger2 = Ledger()
    assert ex.expand_need( "n", lambda s, p: "garbage", ledger2, "m" ) is None and list( ledger2.rows.values() ) == [ "garbage" ]


def test_union_rank_brings_the_known_answer_into_the_list_when_a_later_query_finds_it():
    first = { "code": [ "x1", "x2", "x3" ], "vector": [ "x2", "x1", "x3" ] }
    later = { "code": [ "k", "x1" ], "vector": [ "k", "x2" ] }
    out = ex.union_rank( [ first, later ], "k", FUSION )
    assert out == { "before": None, "after": 3, "enters_before": False, "enters_after": True }      # k beats x3 and loses to x1 and x2, which sit in several lists
    assert ex.union_rank( [ first, later ], "x3", FUSION )[ "before" ] == 3


def test_union_rank_counts_the_shortlist_cut_at_128():
    ids = [ f"i{n}" for n in range( 200 ) ]
    out = ex.union_rank( [ { "code": ids } ], "i150", FUSION )
    assert out[ "before" ] == 151 and out[ "enters_before" ] is False
    assert ex.union_rank( [ { "code": ids } ], "i100", FUSION )[ "enters_before" ] is True


def rows():
    return [ { "id": "r1", "group": "attribution", "need": "n1", "known_id": "k1" }, { "id": "r2", "group": "yield", "need": "n2", "known_id": "k2" } ]


def test_replay_searches_five_ways_and_skips_a_row_with_an_unreadable_reply():
    searched = [ ]
    def search( q ): searched.append( q ); return { "code": [ "k1", "z" ] } if q != "n1" else { "code": [ "z", "y", "k1" ] }
    def ask( system, prompt ): return GOOD if "n1" in prompt else "garbage"
    out = ex.replay( rows(), ask, Ledger(), search, FUSION, "m" )
    assert searched == [ "n1", "one", "two", "three", "alpha beta" ]
    assert out[ 0 ][ "id" ] == "r1" and out[ 0 ][ "before" ] == 3 and out[ 0 ][ "after" ] == 1 and out[ 0 ][ "unreadable" ] is False
    assert out[ 1 ] == { "id": "r2", "group": "yield", "unreadable": True }


def test_summarize_counts_each_group_lifted_lowered_and_unreadable():
    results = [ { "group": "a", "unreadable": False, "before": 200, "after": 5, "enters_before": False, "enters_after": True },
                { "group": "a", "unreadable": False, "before": None, "after": 9, "enters_before": False, "enters_after": True },
                { "group": "a", "unreadable": False, "before": 4, "after": 4, "enters_before": True, "enters_after": True },
                { "group": "b", "unreadable": False, "before": 3, "after": 40, "enters_before": True, "enters_after": True },
                { "group": "b", "unreadable": False, "before": 3, "after": None, "enters_before": True, "enters_after": False },
                { "group": "b", "unreadable": False, "before": None, "after": None, "enters_before": False, "enters_after": False },
                { "group": "b", "unreadable": True } ]
    assert ex.summarize( results ) == { "a": { "needs": 3, "unreadable": 0, "enter_before": 1, "enter_after": 3, "lifted": 2, "lowered": 0 },
                                        "b": { "needs": 4, "unreadable": 1, "enter_before": 2, "enter_after": 1, "lifted": 0, "lowered": 2 } }
