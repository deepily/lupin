#!/usr/bin/env python3
"""
Unit tests for the console-tee fixture capture script.

Why this file exists, and why it is not about the coverage number
----------------------------------------------------------------
`src/tests/fixtures/cc_transcript/capture_transcript_fixture.py` sits OUTSIDE the
coverage frame: `pyproject.toml`'s `source` list names `src/cosa`, the four `src/lupin_*`
packages and `src/scripts` with its subdirectories, and no entry covers `src/tests`.
That is the config's deliberate position — its omit list's own rationale is "test code,
not a coverage denominator". So the 100% mandate does not reach this file, and saying so
is better than leaving it to be re-derived. (Read from pyproject.toml, not measured by a
coverage run.)

It is tested anyway, for a different reason. The capture script makes two claims a
reader has to be able to trust: that the redaction removes content while preserving
structure, and that the window it cuts is selected by a stated predicate rather than by
eye. Both claims are load-bearing — the first because the fixture goes into git, the
second because A2.9's discrimination depends on the window's size. An untested claim
about a redaction is the wrong kind of untested claim.

The tests below are hermetic: synthetic JSONL in tmp_path, no real transcript, no
network. Reading a real transcript is `main`'s job on an operator's host, and the one
test that exercises `main` feeds it synthetic files.

Venue: :7999-eligible — pure functions, tmp_path only, sub-second.
"""

import importlib.util
import json
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

_SCRIPT_PATH = os.path.join(
    _src_path, "tests", "fixtures", "cc_transcript", "capture_transcript_fixture.py"
)


def _load_script_module():
    """
    Import the capture script by path.

    It lives under a fixtures directory with no `__init__.py`, so it is not importable
    as a package member. Loading it by spec is the honest way in — and it keeps the
    script a standalone tool rather than making the test tree a package for one file.

    Requires:
        - _SCRIPT_PATH names the capture script

    Ensures:
        - returns the executed module object
    """
    spec   = importlib.util.spec_from_file_location( "capture_transcript_fixture", _SCRIPT_PATH )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


cap = _load_script_module()


# ── redact_string: the rule the manifest claims ────────────────────────────────

def test_redaction_substitutes_alphanumerics_and_preserves_everything_else():
    """
    The manifest's redaction rule, asserted rather than described.

    This is the claim the committed fixture rests on, so it is pinned to a literal
    rather than derived from the function — a comparison whose two sides both come from
    `redact_string` would be a tautology wearing an assertion's clothes.
    """
    assert cap.redact_string( "abcXYZ019" )    == "xxxXXX777"
    assert cap.redact_string( "a-b_c.d/e" )    == "x-x_x.x/x"
    assert cap.redact_string( "line1\nline2" ) == "xxxx7\nxxxx7"
    assert cap.redact_string( "héllo Ωmega" )  == "xéxxx Ωxxxx"
    assert cap.redact_string( "" )             == ""


def test_redaction_preserves_length_exactly():
    """
    Length is preserved because two things measured in bytes depend on it: the byte
    offsets that are the wire contract's only sequence number, and a block's `truncated`
    flag against its budget (A2.4). A shortening redaction would quietly change what the
    fixture can test.
    """
    for sample in ( "sk-ant-api03-SECRET", "/mnt/DATA01/include/www", "x" * 500, "ñ7\tz" ):
        assert len( cap.redact_string( sample ) ) == len( sample )


def test_a_secret_shaped_string_does_not_survive():
    """
    A negative control with a positive control beside it: the same call that leaves no
    trace of the secret does leave the punctuation, so the absence is redaction rather
    than an empty return.
    """
    redacted = cap.redact_string( "sk-ant-api03-abcDEF123" )
    assert "sk-ant"  not in redacted
    assert "abcDEF"  not in redacted
    assert redacted.count( "-" ) == 3


# ── redact_node: structure survives, content does not ──────────────────────────

def test_structural_keys_pass_through_and_content_keys_do_not():
    """
    The mapper reads `type`, `role`, block `type` and tool `name`; redacting those would
    turn the fixture into noise the mapper cannot parse at all — a fixture that fails
    every implementation equally, which measures nothing.
    """
    node = {
        "type"    : "assistant",
        "cwd"     : "/mnt/DATA01/secret/path",
        "message" : {
            "role"    : "assistant",
            "content" : [ { "type": "tool_use", "name": "Bash", "input": { "command": "cat .env" } } ],
        },
    }
    out = cap.redact_node( node )

    assert out[ "type" ]                            == "assistant"
    assert out[ "message" ][ "role" ]               == "assistant"
    assert out[ "message" ][ "content" ][ 0 ][ "type" ] == "tool_use"
    assert out[ "message" ][ "content" ][ 0 ][ "name" ] == "Bash"

    assert "DATA01" not in out[ "cwd" ]
    assert ".env"   not in json.dumps( out )
    # the path's four separators survive, so the redaction is a substitution not a deletion
    assert out[ "cwd" ] == "/xxx/XXXX77/xxxxxx/xxxx"


def test_non_string_leaves_are_returned_unchanged():
    """Numbers, booleans and None carry no content to redact and no structure to lose."""
    node = { "n": 42, "f": 1.5, "b": True, "z": None, "empty_list": [], "empty_dict": {} }
    assert cap.redact_node( node ) == node


def test_key_sets_and_list_lengths_are_preserved():
    """
    A redaction that dropped or added a key would change the record's SHAPE, and the
    mapper branches on shape. Asserted as a whole-tree property, not per field.
    """
    node = { "a": "xx", "b": [ "one", "two", "three" ], "c": { "d": "e", "f": [ { "g": "h" } ] } }
    out  = cap.redact_node( node )
    assert set( out ) == set( node )
    assert len( out[ "b" ] ) == 3
    assert set( out[ "c" ] ) == { "d", "f" }
    assert set( out[ "c" ][ "f" ][ 0 ] ) == { "g" }


def test_a_string_inside_a_list_is_redacted_under_its_parent_key():
    """
    A list's members are reached through the list's own key. `type` is structural, so a
    bare list of type strings must survive — this pins which key a list member inherits,
    which is the one place the recursion could plausibly be wrong either way.
    """
    assert cap.redact_node( { "type": [ "assistant", "user" ] } ) == { "type": [ "assistant", "user" ] }
    assert cap.redact_node( { "notes": [ "abc" ] } )              == { "notes": [ "xxx" ] }


# ── read_records ──────────────────────────────────────────────────────────────

def _write_jsonl( tmp_path, name, lines ):
    path = tmp_path / name
    path.write_text( "\n".join( lines ) + "\n", encoding="utf-8" )
    return str( path )


def test_read_records_returns_dicts_and_counts_what_it_skipped( tmp_path ):
    """
    The skip count is returned rather than swallowed, and the manifest records it. A
    reader who cannot see how many lines were unparseable cannot tell a clean source
    from a damaged one.
    """
    path = _write_jsonl( tmp_path, "t.jsonl", [
        json.dumps( { "type": "user" } ),
        "",
        "   ",
        "{not json",
        json.dumps( [ 1, 2 ] ),
        json.dumps( "a bare string" ),
        json.dumps( { "type": "assistant" } ),
    ] )
    pairs, skipped = cap.read_records( path )
    assert [ r[ "type" ] for r, _ in pairs ] == [ "user", "assistant" ]
    assert skipped == 5
    # the raw line is carried beside the record — the byte span calculation needs it
    assert pairs[ 0 ][ 1 ] == json.dumps( { "type": "user" } )


# ── message_features and the window predicate ─────────────────────────────────

def test_message_features_ignores_a_record_with_no_message():
    """A bookkeeping record contributes no message-shaped feature, by design."""
    assert cap.message_features( { "type": "atis-latch" } )       == set()
    assert cap.message_features( { "type": "x", "message": "s" } ) == set()


def test_message_features_flags_a_user_record_carrying_a_tool_result():
    """
    The feature that makes the window predicate select for P2's most consequential
    property. An `assistant` record with a tool_result is NOT the same thing, and must
    not satisfy it — otherwise the window could cover the feature without containing the
    record that catches a role-based mapper.
    """
    user_tr = { "type": "user", "message": { "content": [ { "type": "tool_result" } ] } }
    asst_tr = { "type": "assistant", "message": { "content": [ { "type": "tool_result" } ] } }

    assert ( "role_kind_mismatch", "user_carrying_tool_result" ) in cap.message_features( user_tr )
    assert ( "role_kind_mismatch", "user_carrying_tool_result" ) not in cap.message_features( asst_tr )


def test_message_features_reports_both_content_shapes():
    assert ( "shape", "str"  ) in cap.message_features( { "message": { "content": "hello" } } )
    assert ( "shape", "list" ) in cap.message_features( { "message": { "content": [] } } )
    assert ( "shape", "other" ) in cap.message_features( { "message": { "content": 7 } } )


def test_the_window_is_the_smallest_one_covering_every_feature():
    """
    Pinned against a hand-placed layout where the right answer is known by construction.
    The list-shaped records sit at indices 2 and 6 and the string-shaped one at 4, so the
    smallest window carrying both shapes is [2, 5) — three records. The later list-shaped
    record at 6 is the decoy: a search that took the LAST occurrence of each feature would
    return [4, 7), which is the same length and the wrong answer, so the assertion pins the
    indices and not just the width.
    """
    def pair( record ): return ( record, json.dumps( record ) )

    noise   = pair( { "type": "attachment" } )
    shape_s = pair( { "type": "user", "message": { "content": "plain" } } )
    shape_l = pair( { "type": "assistant", "message": { "content": [ { "type": "text" } ] } } )

    pairs = [ noise, noise, shape_l, noise, shape_s, noise, shape_l, noise, noise ]
    start, end = cap.smallest_covering_window( pairs )

    assert ( start, end ) == ( 2, 5 )
    covered = set()
    for record, _ in pairs[ start:end ]: covered |= cap.message_features( record )
    assert ( "shape", "str" )  in covered
    assert ( "shape", "list" ) in covered


def test_the_window_grows_to_the_minimum_byte_span_and_stays_balanced():
    """
    Growth is what makes the fixture bigger than ruling Q6's 64 KB cap. It extends both
    directions so the covering window stays inside the result — a one-sided growth would
    push the interesting records to an edge, where a `tail_bytes` page might not reach
    them.
    """
    def pair( n ): return ( { "type": "attachment", "i": n }, "x" * 99 )

    pairs = [ pair( n ) for n in range( 40 ) ]
    start, end = cap.grow_window_to_min_bytes( pairs, 20, 21, 1000 )

    span = sum( len( raw.encode( "utf-8" ) ) + 1 for _, raw in pairs[ start:end ] )
    assert span >= 1000
    assert start < 20 and end > 21, "growth was one-sided"


def test_growth_stops_at_the_file_rather_than_looping_forever():
    """
    The termination case: a minimum larger than the whole file returns the whole file.
    Without this branch the loop cannot end, so it is watched rather than assumed.
    """
    pairs = [ ( { "type": "x" }, "y" ) for _ in range( 3 ) ]
    assert cap.grow_window_to_min_bytes( pairs, 1, 2, 10_000_000 ) == ( 0, 3 )


def test_growth_is_a_no_op_when_the_window_already_meets_the_minimum():
    pairs = [ ( { "type": "x" }, "y" * 50 ) for _ in range( 10 ) ]
    assert cap.grow_window_to_min_bytes( pairs, 2, 6, 10 ) == ( 2, 6 )


# ── census ────────────────────────────────────────────────────────────────────

def test_census_counts_the_properties_the_manifest_publishes():
    """
    Read the data before the assertions: the counts below are distinct on purpose, so a
    census that summed two facets instead of keeping them apart would be caught. A
    census where every number were equal could not tell them apart.
    """
    records = [
        { "type": "user",      "message": { "content": [ { "type": "tool_result" } ] } },
        { "type": "user",      "message": { "content": "a human turn" } },
        { "type": "assistant", "message": { "content": [ { "type": "text" }, { "type": "thinking" }, { "type": "tool_use" } ] } },
        { "type": "atis-latch" },
        { "type": "atis-latch" },
        { "type": "atis-latch" },
    ]
    out = cap.census( records )

    assert out[ "record_count" ]                      == 6
    assert out[ "record_types" ]                      == { "assistant": 1, "atis-latch": 3, "user": 2 }
    assert out[ "content_shapes" ]                    == { "list": 2, "str": 1 }
    assert out[ "block_kinds" ]                       == { "text": 1, "thinking": 1, "tool_result": 1, "tool_use": 1 }
    assert out[ "user_records_carrying_tool_result" ] == 1


def test_census_records_a_content_shape_that_is_neither_string_nor_list():
    """An unexpected shape is NAMED in the census rather than silently uncounted."""
    out = cap.census( [ { "type": "user", "message": { "content": 7 } } ] )
    assert out[ "content_shapes" ] == { "int": 1 }


def test_census_skips_non_dict_blocks_without_erroring():
    """Real transcripts contain surprises; a census that raises cannot report one."""
    out = cap.census( [ { "type": "user", "message": { "content": [ "bare", 7, None, { "type": "text" } ] } } ] )
    assert out[ "block_kinds" ] == { "text": 1 }


# ── write_fixture and discover_transcripts ────────────────────────────────────

def test_write_fixture_is_newline_terminated_and_reports_its_own_sha( tmp_path ):
    """
    The returned sha is what the manifest commits, so it must be the sha of the bytes
    actually written — computed over the same buffer, then verified here by re-reading
    the file rather than by trusting the return.
    """
    import hashlib

    out_path = str( tmp_path / "out.jsonl" )
    size, digest = cap.write_fixture( out_path, [ { "type": "user" }, { "type": "assistant" } ] )

    raw = open( out_path, "rb" ).read()
    assert len( raw ) == size
    assert hashlib.sha256( raw ).hexdigest() == digest
    assert raw.endswith( b"\n" )
    assert raw.count( b"\n" ) == 2


def test_write_fixture_keeps_non_ascii_unescaped( tmp_path ):
    """
    `ensure_ascii=False` is deliberate: a fixture whose unicode were \\u-escaped would be
    a different byte length and a different parse exercise from the real file.
    """
    out_path = str( tmp_path / "u.jsonl" )
    cap.write_fixture( out_path, [ { "type": "user", "note": "Ωmega" } ] )
    assert "Ωmega" in open( out_path, encoding="utf-8" ).read()


def test_discover_transcripts_returns_nothing_for_a_missing_root( tmp_path ):
    assert cap.discover_transcripts( str( tmp_path / "nope" ) ) == []


def test_discover_transcripts_finds_jsonl_largest_first( tmp_path ):
    """Largest-first matters: the breadth pass takes the first sources it is handed."""
    root = tmp_path / "projects"
    ( root / "proj-a" ).mkdir( parents=True )
    ( root / "proj-b" ).mkdir( parents=True )
    ( root / "proj-a" / "small.jsonl" ).write_text( "x" * 10 )
    ( root / "proj-b" / "big.jsonl" ).write_text( "x" * 100 )
    ( root / "proj-a" / "ignored.txt" ).write_text( "x" * 1000 )
    ( root / "loose.jsonl" ).write_text( "x" * 5000 )   # not inside a project dir

    found = [ os.path.basename( p ) for p in cap.discover_transcripts( str( root ) ) ]
    assert found == [ "big.jsonl", "small.jsonl" ]


# ── main ──────────────────────────────────────────────────────────────────────

def test_main_writes_two_fixtures_and_a_manifest( tmp_path, capsys ):
    """
    End to end over synthetic sources, which is the only way this runs off an operator's
    host. It asserts the manifest's own claims about the files beside it — the same pin
    the committed fixture's guard applies.
    """
    import hashlib

    source = _write_jsonl( tmp_path, "source.jsonl", [
        json.dumps( { "type": "attachment" } ),
        json.dumps( { "type": "user",      "message": { "content": "a human turn" } } ),
        json.dumps( { "type": "assistant", "message": { "content": [ { "type": "text" } ] } } ),
        json.dumps( { "type": "user",      "message": { "content": [ { "type": "tool_result" } ] } } ),
        json.dumps( { "type": "attachment" } ),
    ] )
    extra = _write_jsonl( tmp_path, "extra.jsonl", [
        json.dumps( { "type": "cost-state", "cost": 1 } ),
        json.dumps( { "type": "attachment" } ),
    ] )
    out_dir = str( tmp_path / "out" )

    rc = cap.main( [ "--source", source, "--extra", extra, "--out-dir", out_dir, "--min-bytes", "0" ] )
    assert rc == 0

    manifest = json.load( open( os.path.join( out_dir, "manifest.json" ), encoding="utf-8" ) )
    assert manifest[ "primary" ][ "source_basename" ] == "source.jsonl"
    assert manifest[ "primary" ][ "census" ][ "user_records_carrying_tool_result" ] == 1
    # Breadth took every type the primary WINDOW lacks — which includes `attachment`,
    # because the covering window is [1, 4) and both attachment records sit outside it.
    # That is the script behaving correctly and this expectation being written from the
    # source file rather than from the window the predicate actually cuts.
    assert manifest[ "breadth" ][ "census" ][ "record_types" ] == { "attachment": 1, "cost-state": 1 }

    for slot, name in ( ( "primary", "primary.jsonl" ), ( "breadth", "breadth.jsonl" ) ):
        raw = open( os.path.join( out_dir, name ), "rb" ).read()
        assert hashlib.sha256( raw ).hexdigest() == manifest[ slot ][ "sha256" ]

    assert "manifest" in capsys.readouterr().out


def test_main_refuses_a_source_with_no_parseable_records( tmp_path, capsys ):
    """
    A refusal that names what it did not do, rather than writing an empty fixture and
    exiting 0 — the failure mode CLAUDE.md § "Reading a result" warns about, where a
    no-op and a success print the same status.
    """
    empty = _write_jsonl( tmp_path, "empty.jsonl", [ "{not json", "" ] )
    rc = cap.main( [ "--source", empty, "--out-dir", str( tmp_path / "o" ) ] )
    assert rc == 1
    assert "REFUSED" in capsys.readouterr().err
    assert not os.path.exists( os.path.join( str( tmp_path / "o" ), "primary.jsonl" ) )


def test_main_can_discover_extra_sources_itself( tmp_path, monkeypatch, capsys ):
    """
    `--auto-extra` is the path the committed fixture was actually captured with, so it is
    exercised rather than left to the operator's shell history. The discovery root is
    redirected into tmp_path — the real one is the host's home directory.
    """
    home_projects = tmp_path / "projects"
    ( home_projects / "p" ).mkdir( parents=True )
    ( home_projects / "p" / "other.jsonl" ).write_text(
        json.dumps( { "type": "worktree-state" } ) + "\n", encoding="utf-8"
    )

    source = _write_jsonl( tmp_path, "source.jsonl", [
        json.dumps( { "type": "user",      "message": { "content": "turn" } } ),
        json.dumps( { "type": "assistant", "message": { "content": [ { "type": "text" } ] } } ),
        json.dumps( { "type": "user",      "message": { "content": [ { "type": "tool_result" } ] } } ),
    ] )

    monkeypatch.setattr( os.path, "expanduser", lambda p: str( home_projects ) if p == "~/.claude/projects" else p )

    rc = cap.main( [ "--source", source, "--auto-extra", "--out-dir", str( tmp_path / "o" ), "--min-bytes", "0" ] )
    assert rc == 0
    manifest = json.load( open( os.path.join( str( tmp_path / "o" ), "manifest.json" ), encoding="utf-8" ) )
    assert manifest[ "breadth" ][ "origins" ] == { "worktree-state": "other.jsonl" }


def test_auto_extra_never_draws_from_the_source_itself( tmp_path, monkeypatch ):
    """
    The source is skipped by realpath during discovery. Without that, the breadth file
    would re-cut records the primary window already holds — and a symlinked path would
    slip past a string comparison, which is why the script compares realpaths.
    """
    home_projects = tmp_path / "projects"
    ( home_projects / "p" ).mkdir( parents=True )
    real = home_projects / "p" / "real.jsonl"
    real.write_text(
        json.dumps( { "type": "user",      "message": { "content": "turn" } } ) + "\n" +
        json.dumps( { "type": "assistant", "message": { "content": [ { "type": "text" } ] } } ) + "\n" +
        json.dumps( { "type": "user",      "message": { "content": [ { "type": "tool_result" } ] } } ) + "\n",
        encoding="utf-8",
    )
    link = tmp_path / "link.jsonl"
    link.symlink_to( real )

    monkeypatch.setattr( os.path, "expanduser", lambda p: str( home_projects ) if p == "~/.claude/projects" else p )

    rc = cap.main( [ "--source", str( link ), "--auto-extra", "--out-dir", str( tmp_path / "o" ), "--min-bytes", "0" ] )
    assert rc == 0
    manifest = json.load( open( os.path.join( str( tmp_path / "o" ), "manifest.json" ), encoding="utf-8" ) )
    assert manifest[ "breadth" ][ "census" ][ "record_count" ] == 0, (
        "the source was reached again through its symlink, so breadth re-cut it"
    )


# ── the branches the first pass left unwatched ─────────────────────────────────
#
# Added after measuring: the file read 97% (2 statements, 4 partial branches) and the
# gaps were all in loop and fallback arms. CLAUDE.md § Coverage — a branch absent from
# the report is never-measured, not zero, so each one gets a case that names what it is.

def test_message_features_walks_every_block_in_a_multi_block_message():
    """
    The loop's second iteration. A single-block message exercises the body once and
    leaves the back edge unwatched, so a `break` mistakenly placed in that loop would
    pass every other test in this file.
    """
    record = { "type": "assistant", "message": { "content": [
        { "type": "text" }, { "type": "thinking" }, { "type": "tool_use" },
    ] } }
    kinds = { value for facet, value in cap.message_features( record ) if facet == "kind" }
    assert kinds == { "text", "thinking", "tool_use" }


def test_message_features_skips_a_non_dict_block():
    """
    The `continue` arm. Real transcripts contain bare strings inside a content list, and
    the window predicate must step over one rather than raising — a raise here would
    abort the capture on a perfectly ordinary source file.
    """
    record = { "type": "assistant", "message": { "content": [ "bare", 7, None, { "type": "text" } ] } }
    kinds  = { value for facet, value in cap.message_features( record ) if facet == "kind" }
    assert kinds == { "text" }


def test_growth_extends_forward_only_when_the_window_starts_at_the_file_head():
    """
    The fallback arm: balanced growth wants to step backward, cannot, and must take the
    forward step instead rather than spinning. A window already at index 0 is the case.
    """
    pairs = [ ( { "type": "x" }, "y" * 20 ) for _ in range( 10 ) ]
    start, end = cap.grow_window_to_min_bytes( pairs, 0, 1, 100 )
    assert start == 0 and end >= 5


def test_growth_extends_backward_only_when_the_window_ends_at_the_file_tail():
    """The mirror fallback arm, for a window already touching the last record."""
    pairs = [ ( { "type": "x" }, "y" * 20 ) for _ in range( 10 ) ]
    start, end = cap.grow_window_to_min_bytes( pairs, 9, 10, 100 )
    assert end == 10 and start <= 5


def test_auto_extra_stops_at_the_max_sources_cap( tmp_path, monkeypatch ):
    """
    The cap's `break`. Without a case the loop only ever ends by exhausting the roster,
    so a cap that never fired would look identical.
    """
    home_projects = tmp_path / "projects"
    ( home_projects / "p" ).mkdir( parents=True )
    for index, record_type in enumerate( ( "worktree-state", "cost-state", "relocated" ) ):
        # descending size so discovery order is deterministic
        body = json.dumps( { "type": record_type, "pad": "z" * ( 300 - index * 100 ) } ) + "\n"
        ( home_projects / "p" / f"s{index}.jsonl" ).write_text( body, encoding="utf-8" )

    source = _write_jsonl( tmp_path, "source.jsonl", [
        json.dumps( { "type": "user",      "message": { "content": "turn" } } ),
        json.dumps( { "type": "assistant", "message": { "content": [ { "type": "text" } ] } } ),
        json.dumps( { "type": "user",      "message": { "content": [ { "type": "tool_result" } ] } } ),
    ] )
    monkeypatch.setattr( os.path, "expanduser", lambda p: str( home_projects ) if p == "~/.claude/projects" else p )

    rc = cap.main( [ "--source", source, "--auto-extra", "--max-extra-sources", "1",
                     "--out-dir", str( tmp_path / "o" ), "--min-bytes", "0" ] )
    assert rc == 0
    manifest = json.load( open( os.path.join( str( tmp_path / "o" ), "manifest.json" ), encoding="utf-8" ) )
    assert manifest[ "breadth" ][ "census" ][ "record_types" ] == { "worktree-state": 1 }, (
        "the cap did not stop discovery at one source"
    )


def test_breadth_skips_an_extra_record_whose_type_the_window_already_has( tmp_path ):
    """
    The dedupe `continue`. The breadth file's whole purpose is types the primary window
    lacks, so a record whose type is already covered must be passed over — and the only
    way to see that happen is to offer one.
    """
    source = _write_jsonl( tmp_path, "source.jsonl", [
        json.dumps( { "type": "user",      "message": { "content": "turn" } } ),
        json.dumps( { "type": "assistant", "message": { "content": [ { "type": "text" } ] } } ),
        json.dumps( { "type": "user",      "message": { "content": [ { "type": "tool_result" } ] } } ),
    ] )
    extra = _write_jsonl( tmp_path, "extra.jsonl", [
        json.dumps( { "type": "assistant", "message": { "content": [ { "type": "text" } ] } } ),  # already covered
        json.dumps( { "type": "cost-state" } ),                                                  # new
    ] )

    rc = cap.main( [ "--source", source, "--extra", extra,
                     "--out-dir", str( tmp_path / "o" ), "--min-bytes", "0" ] )
    assert rc == 0
    manifest = json.load( open( os.path.join( str( tmp_path / "o" ), "manifest.json" ), encoding="utf-8" ) )
    assert manifest[ "breadth" ][ "census" ][ "record_types" ] == { "cost-state": 1 }


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
