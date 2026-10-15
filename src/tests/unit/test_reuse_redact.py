"""
The need redactor (candidate-stage plan, section 6, the redaction rulings).

Each kind has a positive and a negative control. Expected strings are written out literally.
A redactor that blanks too much or too little fails on its own output, not on a second copy of its rule.
"""
import pytest

from lupin_mcp import reuse_redact as rr
from lupin_mcp.reuse_redact import redact_need

ROUTES = ( "/api/v2/submit", "/api/queue/{id}", "/api/auth/{provider}/callback" )


def red( text, routes=() ): return redact_need( text, routes )[ 0 ]


def kinds( text, routes=() ): return [ ( h[ "kind" ], h[ "count" ] ) for h in redact_need( text, routes )[ 2 ] ]


# --- one positive and one negative control per kind ---

@pytest.mark.parametrize( "text, expected, kind", [
    ( "mail bob@example.com now",                 "mail [email] now",            "email" ),
    ( "mail bob@example.com.",                    "mail [email].",               "email" ),
    ( "see https://a.example/c/d.",               "see [url].",                  "url" ),
    ( "see www.example.com/x, then",              "see [url], then",             "url" ),
    ( "host 10.0.0.1. up",                        "host [ip]. up",               "ip" ),
    ( "v6 fe80::1 up",                            "v6 [ip] up",                  "ip" ),
    ( "loopback ::1 up",                          "loopback [ip] up",            "ip" ),
    ( "read /etc/passwd, then",                   "read [path], then",           "path" ),
    ( "open '/home/rick/x.py'",                   "open '[path]'",               "path" ),
    ( "in ~/proj/x and $HOME/a and ${HOME}/b",    "in [path] and [path] and [path]", "path" ),
    ( "at C:\\Users\\x and \\\\srv\\share\\f",    "at [path] and [path]",        "path" ),
    ( "key sk-abcdefghijklm used",                "key [secret] used",           "secret" ),
    ( "id AKIAABCDEFGHIJKLMNOP",                  "id [secret]",                 "secret" ),
    ( "tok " + "a1b2c3d4" * 5,                    "tok [secret]",                "secret" ),
] )
def test_each_kind_is_blanked_with_its_own_placeholder( text, expected, kind ):
    assert red( text ) == expected
    assert kinds( text )[ 0 ][ 0 ] == kind


@pytest.mark.parametrize( "text", [
    "and/or", "a fraction 1/2", "src/cosa/x.py", "./a/b and ../c/d", "just /etc alone", "a@b with no domain",
    "time 10:30:45:20", "a:b:c:d", "Foo::bar", "version 1.2.3", "bad ip 999.1.1.1", "unicode naïve café", "",
] )
def test_text_with_none_of_the_five_kinds_is_returned_unchanged( text ):
    redacted, ranking, hits = redact_need( text )
    assert ( redacted, ranking, hits ) == ( text, text, [] )


def test_identifiers_are_kept_and_the_two_measured_false_positives_stay_fixed():
    for ident in ( "validate_and_normalize_user_input_v2", "buildUserProfileIndexFromRows2", "v2",
                   "a_very_long_kebab-case-name-with-words-and-more-words-1" ):
        assert red( f"call {ident} now" ) == f"call {ident} now"


def test_a_long_mixed_token_with_no_word_structure_is_a_secret():
    assert red( "tok 3f9a0c7e1d4b8a6f2e5c9b0d7a1e4f8c3b6a9d2e" ) == "tok [secret]"
    assert red( "tok Ab1_Cd2_Ef3_Gh4_Ij5_Kl6_Mn7_Op8_Qr9_" + "ZZ" ) == "tok [secret]"       # uppercase runs are not words


def test_an_empty_segment_is_not_word_shaped():
    assert rr._is_word_shaped( "ab__cd" ) is False
    assert rr._is_word_shaped( "ab_cd" ) is True
    assert rr._is_word_shaped( "ab_2" ) is True


# --- addresses ---

def test_an_ipv6_candidate_needs_the_standard_library_to_parse_it_and_a_colon_pair_or_eight_groups():
    assert red( "x 1::2::3 y" ) == "x 1::2::3 y"                      # two compressions: not an address
    assert red( "x :: y" ) == "x :: y"                                # no hex digit
    assert red( "x abcd y" ) == "x abcd y"                            # no colon
    assert red( "x 1:2:3:4:5:6:7:8 y" ) == "x [ip] y"                 # eight groups
    assert red( "x 1:2:3:4:5:6:7 y" ) == "x 1:2:3:4:5:6:7 y"          # seven groups, no compression
    assert red( "x 1:2:3:4:5:6:7:8:9 y" ) == "x 1:2:3:4:5:6:7:8:9 y"  # nine groups
    assert red( "x abc::def y" ) == "x [ip] y"                        # the documented residual: read as an address


def test_an_ipv4_candidate_must_parse():
    assert red( "x 01.2.3.4 y" ) == "x 01.2.3.4 y"
    assert red( "x 192.168.0.256 y" ) == "x 192.168.0.256 y"
    assert red( "x 192.168.0.25 y" ) == "x [ip] y"


# --- paths and routes ---

def test_a_path_whose_trailing_punctuation_shrinks_it_below_two_segments_is_left_alone():
    assert red( "see /etc/. now" ) == "see /etc/. now"


def test_a_kept_route_a_templated_route_and_a_prefix_of_a_route_stay_visible():
    assert red( "wrap /api/v2/submit please", ROUTES ) == "wrap /api/v2/submit please"
    assert red( "wrap /api/queue/7 please", ROUTES ) == "wrap /api/queue/7 please"
    assert red( "under /api/queue now", ROUTES ) == "under /api/queue now"


def test_a_route_is_kept_only_when_it_matches_a_known_route():
    assert red( "wrap /api/v2/other", ROUTES ) == "wrap [path]"
    assert red( "wrap /api/v2/submit/extra", ROUTES ) == "wrap [path]"
    assert red( "wrap /home/rick/api/v2/submit", ROUTES ) == "wrap [path]"
    assert red( "read /etc/passwd", ROUTES ) == "read [path]"


def test_an_empty_route_list_redacts_every_absolute_path():
    assert red( "wrap /api/v2/submit" ) == "wrap [path]"
    assert red( "wrap /api/v2/submit", () ) == "wrap [path]"


@pytest.mark.parametrize( "text", [
    "/api/queue/alice@example.com",
    "/api/queue/sk-abcdefghijklm",
    "/api/queue/10.0.0.1",
    "/api/v2/submit?to=bob@example.com",
] )
def test_a_kept_route_is_still_screened_for_the_other_four_kinds( text ):
    assert red( text, ROUTES ) == "[path]"


def test_a_url_inside_a_route_is_still_redacted_as_a_url():
    assert red( "/api/queue/https://x.example/y", ROUTES ) == "/api/queue/[url]"


def test_a_path_that_holds_an_email_is_one_path_and_not_two_spans():
    redacted, _, hits = redact_need( "see /home/alice@example.com/x ok" )
    assert redacted == "see [path] ok"
    assert hits == [ { "kind": "path", "count": 1 } ]


# --- outputs ---

def test_hits_are_counted_by_kind_and_sorted():
    redacted, ranking, hits = redact_need( "mail a@b.co or c@d.co from 10.0.0.1 at /etc/hosts" )
    assert redacted == "mail [email] or [email] from [ip] at [path]"
    assert ranking == "mail   or   from   at  "
    assert hits == [ { "kind": "email", "count": 2 }, { "kind": "ip", "count": 1 }, { "kind": "path", "count": 1 } ]


def test_ranking_text_carries_no_placeholder_word_and_keeps_the_rest_byte_for_byte():
    _, ranking, _ = redact_need( "read the file /etc/passwd for bob@example.com" )
    assert ranking == "read the file   for  "
    for word in ( "path", "email", "url", "secret", "ip" ): assert f"[{word}]" not in ranking


def test_redaction_is_idempotent_over_every_kind_at_once():
    text = ( "mail bob@example.com see https://a.example/c at 10.0.0.1 fe80::1 read /etc/passwd ~/x C:\\a\\b "
             "sk-abcdefghijklm /api/v2/submit /api/queue/alice@example.com" )
    once = red( text, ROUTES )
    assert red( once, ROUTES ) == once
    for placeholder in rr.PLACEHOLDERS.values(): assert placeholder in once


def test_placeholders_match_none_of_the_five_kinds():
    for placeholder in rr.PLACEHOLDERS.values():
        assert redact_need( placeholder, ROUTES ) == ( placeholder, placeholder, [] )


def test_no_pattern_of_the_five_kinds_survives_a_generated_corpus():
    pieces = [ "bob@example.com", "https://a.example/x", "10.0.0.1", "fe80::1", "/etc/passwd", "~/x", "C:\\a\\b", "sk-abcdefghijklm", "word", "and/or", "1/2" ]
    for i, a in enumerate( pieces ):
        for b in pieces[ i: ]:
            out = red( f"{a} {b}, {a}.", ROUTES )
            again = redact_need( out, ROUTES )
            assert again[ 0 ] == out and again[ 2 ] == []


def test_a_long_run_of_one_letter_is_linear_not_exponential():
    text = "a" * 20000 + "!"                                           # a nested repeat in the word test would never return
    assert red( text ) == text


# --- the route list ---

def test_routes_from_text_reads_the_path_of_each_route_line():
    text = "GET /api/v2/submit -> cosa.rest.v2.submit  (src/cosa/rest/v2/x.py)\n" \
           "POST /api/queue/{id} -> cosa.rest.q  (src/cosa/rest/q.py)\n" \
           "GET /api/v2/submit -> cosa.rest.v2.submit_again  (src/cosa/rest/v2/y.py)\n" \
           "not a route line\n"
    assert rr.routes_from_text( text ) == ( "/api/queue/{id}", "/api/v2/submit" )
    assert rr.routes_from_text( "" ) == ()


# --- review fixes: query strings, tilde-number text, acronym identifiers ---

@pytest.mark.parametrize( "need", [ "go /api/v2/submit?session=zz91 now", "go /api/v2/submit#token=abc now", "go /api/queue/7?x=1 now" ] )
def test_a_known_route_that_carries_a_query_or_fragment_is_redacted_whole( need ):
    assert red( need, ROUTES ) == need.split( " " )[ 0 ] + " [path] now"
    assert "zz91" not in red( need, ROUTES ) and "abc" not in red( need, ROUTES )


def test_the_same_route_without_a_query_is_still_kept():
    assert red( "go /api/v2/submit now", ROUTES ) == "go /api/v2/submit now"


@pytest.mark.parametrize( "text", [ "a score of ~5/10 here", "about ~2/3 of it", "roughly ~1.5/2 done" ] )
def test_a_tilde_number_ratio_is_not_a_home_path( text ):
    assert red( text ) == text


@pytest.mark.parametrize( "text, expected", [ ( "see ~/notes/a.txt", "see [path]" ), ( "see ~rick/notes/a.txt", "see [path]" ), ( "see ${HOME}/x", "see [path]" ) ] )
def test_a_home_path_is_still_redacted( text, expected ):
    assert red( text ) == expected


def test_an_identifier_with_an_acronym_run_is_kept_and_a_bare_capital_run_is_not_a_word():
    assert red( "call getHTTPResponseHeaderValueByName2 now" ) == "call getHTTPResponseHeaderValueByName2 now"
    assert rr._is_word_shaped( "getHTTPResponseHeader2" ) is True
    assert rr._is_word_shaped( "ZZ" ) is False
    assert red( "tok 9aB3dE7fG1hJ5kL8mN2pQ4rS6tU0vW9xY3zA" ) == "tok [secret]"


# --- the finders stay linear, and stay the same finders ---

N_WORST = 200000
WORST_SHAPES = {
    "a run of word characters"   : "a" * N_WORST,
    "dotted labels"              : "a." * ( N_WORST // 2 ),
    "dashed labels"              : "a-" * ( N_WORST // 2 ),
    "scheme characters"          : "ab+" * ( N_WORST // 3 ),
    "at signs and domains"       : "a@b." * ( N_WORST // 4 ),
    "bare scheme separators"     : "://" * ( N_WORST // 3 ),
    "short schemes"              : "a://" * ( N_WORST // 4 ),
    "secret prefixes"            : "sk-" * ( N_WORST // 3 ),
    "many short emails"          : "a@b.co " * ( N_WORST // 7 ),
    "many short paths"           : "/a/b " * ( N_WORST // 5 ),
}


@pytest.mark.parametrize( "shape", sorted( WORST_SHAPES ) )
def test_two_hundred_thousand_characters_of_a_worst_case_shape_finish_well_under_a_second( shape ):
    import time
    start = time.perf_counter()
    rr.redact_need( WORST_SHAPES[ shape ], ROUTES )
    assert time.perf_counter() - start < 1.0, shape      # measured 0.2 s or less; a quadratic finder takes 8 to 18 s here


def test_the_email_and_url_finders_return_what_the_original_patterns_returned():
    import random, re
    url_old   = re.compile( r"(?:\b[A-Za-z][A-Za-z0-9+.-]*://|\bwww\.)\S+" )
    email_old = re.compile( r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+" )
    pieces    = list( "ab1_.+-@:/ www.http://\u00e9 ,;)\n" ) + [ "://", "www.", "@", "a.b", "http", "\u00df", "a://", "@b.c" ]
    rng       = random.Random( 31 )
    checked   = 0
    for _ in range( 6000 ):
        text = "".join( rng.choice( pieces ) for _ in range( rng.randint( 0, 22 ) ) )
        assert rr._urls( text )   == [ ( m.start(), rr._trim( text, m.start(), m.end() ) ) for m in url_old.finditer( text ) ], repr( text )
        assert rr._emails( text ) == [ ( m.start(), m.end() ) for m in email_old.finditer( text ) ], repr( text )
        checked += 1
    assert checked == 6000


def test_an_address_whose_local_part_follows_another_address_is_redacted_too():
    assert red( "pq@x.y.z+@w.vv" ) == "[email][email]"                              # the second local part is "+", as a left-to-right scan reads it
    assert red( "see b.wwww.@a.b. now" ) == "see [email]. now"
    assert red( "a@b.co,c@d.org" ) == "[email],[email]"


def _reference_redact( text, routes ):
    """Ensures: returns the text redacted with the first version's overlap rule."""
    finders = { "url": rr._urls, "path": rr._paths, "email": rr._emails, "secret": rr._secrets, "ip": rr._ips }
    cand = []
    for rank, kind in enumerate( rr.ORDER ):
        for s, e in finders[ kind ]( text ):
            if kind == "path" and text[ s ] == "/" and rr.re.search( r"[?#]", text[ s:e ] ) is None and rr._is_known_route( text[ s:e ], routes ): continue
            cand.append( ( rank, s, e, kind ) )
    taken = []
    for rank, s, e, kind in sorted( cand ):
        if not any( s < te and ts < e for ts, te, _ in taken ): taken.append( ( s, e, kind ) )
    taken.sort()
    out, at = [], 0
    for s, e, kind in taken:
        out.append( text[ at:s ] + rr.PLACEHOLDERS[ kind ] )
        at = e
    return "".join( out ) + text[ at: ]


@pytest.mark.parametrize( "text, expected", [
    ( ":// ::1a@b.c",              ":// ::[email]" ),
    ( "@b.c@www.x@y.com~/::1@",    "@b.c@[url]" ),
    ( "~/www.x@y.comb.c~/://",     "~/[url]" ),
] )
def test_a_later_span_that_reaches_back_into_a_taken_span_is_dropped( text, expected ):
    assert red( text ) == expected == _reference_redact( text, () )


def test_the_overlap_resolution_matches_the_first_versions_rule_on_random_text():
    import random
    pieces = list( "ab1_.+-@:/ ~\\n" ) + [ "://", "www.", "@", "a.b", "::1", "~/", "http", "a@b.c", "/a/b", "1.2.3.4", "sk-abcdefghij", "x.y.com" ]
    rng    = random.Random( 5 )
    for _ in range( 8000 ):
        text = "".join( rng.choice( pieces ) for _ in range( rng.randint( 0, 14 ) ) )
        assert red( text, ROUTES ) == _reference_redact( text, ROUTES ), repr( text )
