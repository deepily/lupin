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
    assert red( "with /api/v2/submit?x=1 now", ROUTES ) == "with /api/v2/submit?x=1 now"


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
