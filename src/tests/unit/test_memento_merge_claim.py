"""
Unit tests for the merge-claim check (row 0c80f26d).

The check refuses a memento whose most consequential line — "there is still
unmerged work" — the repo can PROVE false, because it names a commit already in
HEAD. That line is the one a successor acts on first, and it goes stale within
minutes: it describes somebody else's pending action, and the author is no
longer running when they take it.

Coverage target is 100% lines AND branches on memento_merge_claim.py, plus the
new gate inside verify_seat_memento. The one exclusion is the fail-open
`except Exception` backstop, which carries a same-line pragma.
"""
import datetime

import pytest

from lupin_mcp.memento_merge_claim import (
    find_merge_claims,
    refuted_merge_claim,
    default_ancestry_probe,
)
from lupin_mcp.reap_memento import verify_seat_memento


# The three instances the row records, verbatim in shape. Only the second names
# a commit, which is exactly why the module documents the other two as MISSED.
ROW_INSTANCE_1 = "three commits are unpushed and unmerged"
ROW_INSTANCE_2 = "`f2ee98cf` is the only thing waiting on you"
ROW_INSTANCE_3 = "the seven commits are yours to merge whenever you want them"

# krishna's CORRECT pattern — the command and its reading on one line. It carries
# a sha AND the word "unmerged" and must never be refused for that.
GOOD_LIVE_QUERY = "| `git log 8657cfa9..HEAD` | empty — nothing unmerged on this branch |"


def _merged( sha, repo_root ):
    """Probe stub: every commit is already in HEAD."""
    return True


def _not_merged( sha, repo_root ):
    """Probe stub: no commit is in HEAD yet — every claim still stands."""
    return False


def _unresolvable( sha, repo_root ):
    """Probe stub: git cannot answer (unknown sha, no repo, git missing)."""
    return None


# ---------------------------------------------------------------------------
# find_merge_claims — what couples, and what deliberately does not
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "line", [
    ROW_INSTANCE_2,
    "- **Branch**: `wt-phase2-drift-guard` — **HEAD `df151d7c`**. **UNMERGED and HELD**",
    "`abc1234` is not yet merged",
    "not yet merged: `abc1234`",
    "`abc1234` — yours to merge",
    "`abc1234` still needs merging",
    "pending merge of `abc1234`",
    "awaiting your merge of `abc1234`",
    "`abc1234` is waiting for you",
] )
def test_a_negative_claim_naming_a_commit_is_found( line ):

    found = find_merge_claims( line )
    assert found, line
    assert found[ 0 ][ 1 ] == "abc1234" or len( found[ 0 ][ 1 ] ) >= 7


def test_the_live_query_pattern_is_never_a_claim():
    """Showing the command and its reading is the pattern being ENCOURAGED."""
    assert find_merge_claims( GOOD_LIVE_QUERY ) == []


@pytest.mark.parametrize( "line", [
    "git merge-base --is-ancestor abc1234 HEAD  # nothing unmerged",
    "git branch --merged shows abc1234 — nothing unmerged",
    "task_query says abc1234 is unmerged",
] )
def test_every_live_query_form_is_exempt( line ):

    assert find_merge_claims( line ) == []


def test_a_durable_receipt_is_not_a_claim():
    """`merged at <sha>` is true forever — stripping it would help nobody."""
    assert find_merge_claims( "merged at 4eee90fa" ) == []


@pytest.mark.parametrize( "line", [ ROW_INSTANCE_1, ROW_INSTANCE_3 ] )
def test_a_claim_with_no_commit_is_missed_and_that_is_documented( line ):
    """Two of the row's three instances name no commit, so none can be refuted."""
    assert find_merge_claims( line ) == []


def test_a_commit_too_far_from_the_claim_is_not_coupled():
    """Loose coupling is what took the real-corpus match count from 6 to 124."""
    line = "abc1234 " + ( "x" * 60 ) + " unmerged"
    assert find_merge_claims( line ) == []


def test_a_short_hex_run_is_not_a_commit():

    assert find_merge_claims( "abc123 is unmerged" ) == []


def test_the_line_number_is_one_indexed():

    text  = "header\n\n" + ROW_INSTANCE_2
    found = find_merge_claims( text )
    assert found[ 0 ][ 0 ] == 3


def test_the_offending_line_is_returned_stripped():

    found = find_merge_claims( "   " + ROW_INSTANCE_2 + "   " )
    assert found[ 0 ][ 2 ] == ROW_INSTANCE_2


def test_two_claims_on_two_lines_are_both_found():

    text = ROW_INSTANCE_2 + "\n`abc1234` is not yet merged"
    assert len( find_merge_claims( text ) ) == 2


def test_text_with_no_claim_at_all():

    assert find_merge_claims( "## Memento\n\nAll green. Branch wt-x." ) == []


# ---------------------------------------------------------------------------
# refuted_merge_claim — only a POSITIVE refutation refuses
# ---------------------------------------------------------------------------

def test_a_claim_the_repo_falsifies_is_refused():

    reason = refuted_merge_claim( ROW_INSTANCE_2, "/repo", ancestry_probe=_merged )
    assert reason is not None
    assert "f2ee98cf" in reason
    assert "git log HEAD..<branch>" in reason
    assert "line 1" in reason


def test_a_claim_that_is_still_true_is_allowed():

    assert refuted_merge_claim( ROW_INSTANCE_2, "/repo", ancestry_probe=_not_merged ) is None


def test_an_unresolvable_commit_never_refuses():
    """Cannot refute is ALLOW — a reap path must not strand a seat on a guess."""
    assert refuted_merge_claim( ROW_INSTANCE_2, "/repo", ancestry_probe=_unresolvable ) is None


def test_the_first_refutable_claim_is_the_one_reported():

    text   = "`aaaaaaa` is not yet merged\n`bbbbbbb` is not yet merged"
    reason = refuted_merge_claim( text, "/repo", ancestry_probe=_merged )
    assert "aaaaaaa" in reason
    assert "bbbbbbb" not in reason


def test_a_later_claim_is_still_caught_when_the_first_cannot_be_resolved():

    text   = "`aaaaaaa` is not yet merged\n`bbbbbbb` is not yet merged"
    probe  = lambda sha, root: None if sha == "aaaaaaa" else True
    reason = refuted_merge_claim( text, "/repo", ancestry_probe=probe )
    assert "bbbbbbb" in reason


@pytest.mark.parametrize( "text", [ None, "", 17, [] ] )
def test_a_missing_or_non_string_memento_is_allowed( text ):

    assert refuted_merge_claim( text, "/repo", ancestry_probe=_merged ) is None


def test_the_probe_defaults_to_real_git( tmp_path ):
    """`ancestry_probe=None` resolves to git — an unknown sha cannot refute."""
    assert refuted_merge_claim( ROW_INSTANCE_2, str( tmp_path ) ) is None


# ---------------------------------------------------------------------------
# default_ancestry_probe — against a real, tiny repository
# ---------------------------------------------------------------------------

def _git( tmp_path, *args ):
    import subprocess
    return subprocess.run( [ "git", "-C", str( tmp_path ), *args ], capture_output=True, text=True )


@pytest.fixture
def repo( tmp_path ):
    """A two-commit repo with a second branch holding an un-merged commit."""
    _git( tmp_path, "init", "-q", "-b", "main" )
    _git( tmp_path, "config", "user.email", "t@t" )
    _git( tmp_path, "config", "user.name", "t" )
    ( tmp_path / "a.txt" ).write_text( "one" )
    _git( tmp_path, "add", "a.txt" )
    _git( tmp_path, "commit", "-q", "-m", "first" )
    merged = _git( tmp_path, "rev-parse", "HEAD" ).stdout.strip()
    _git( tmp_path, "checkout", "-q", "-b", "side" )
    ( tmp_path / "b.txt" ).write_text( "two" )
    _git( tmp_path, "add", "b.txt" )
    _git( tmp_path, "commit", "-q", "-m", "second" )
    unmerged = _git( tmp_path, "rev-parse", "HEAD" ).stdout.strip()
    _git( tmp_path, "checkout", "-q", "main" )
    return { "root": str( tmp_path ), "merged": merged, "unmerged": unmerged }


def test_probe_says_true_for_a_commit_already_in_head( repo ):

    assert default_ancestry_probe( repo[ "merged" ], repo[ "root" ] ) is True


def test_probe_says_false_for_a_commit_not_in_head( repo ):

    assert default_ancestry_probe( repo[ "unmerged" ], repo[ "root" ] ) is False


def test_probe_says_none_for_an_unknown_commit( repo ):

    assert default_ancestry_probe( "0" * 40, repo[ "root" ] ) is None


def test_probe_says_none_outside_a_repository( tmp_path ):

    assert default_ancestry_probe( "abc1234", str( tmp_path / "nope" ) ) is None


def test_probe_says_none_when_git_cannot_be_run( monkeypatch ):

    import subprocess
    def boom( *a, **kw ):
        raise OSError( "no git" )
    monkeypatch.setattr( subprocess, "run", boom )
    assert default_ancestry_probe( "abc1234", "/repo" ) is None


def test_a_real_repo_end_to_end_refuses_a_falsified_claim( repo ):
    """No stubs anywhere: real git decides, and it refuses."""
    text   = "`" + repo[ "merged" ][ :8 ] + "` is the only thing waiting on you"
    assert refuted_merge_claim( text, repo[ "root" ] ) is not None


def test_a_real_repo_end_to_end_allows_a_claim_that_still_stands( repo ):

    text = "`" + repo[ "unmerged" ][ :8 ] + "` is the only thing waiting on you"
    assert refuted_merge_claim( text, repo[ "root" ] ) is None


# ---------------------------------------------------------------------------
# The gate inside verify_seat_memento
# ---------------------------------------------------------------------------

WRITTEN_AT = "2026-08-24T20:00:00+00:00"
NOW        = datetime.datetime.fromisoformat( "2026-08-24T20:01:00+00:00" )


def _memento( body ):
    """A memento that passes every pre-existing gate: header, size, freshness."""
    return (
        "<!-- memento-record: session_id=abcd1234 written_at=" + WRITTEN_AT + " -->\n"
        + body + "\n" + ( "filler line to clear the byte floor.\n" * 40 )
    )


def _verify( body, **kw ):
    text = _memento( body )
    return verify_seat_memento(
        "/slot", "abcd1234", NOW, read_text_fn=lambda p: text, **kw
    )


def test_the_gate_is_skipped_without_a_repo_root():
    """`repo_root=None` keeps pure unit verification hermetic."""
    usable, reason = _verify( ROW_INSTANCE_2 )
    assert usable is True
    assert "verified" in reason


def test_an_otherwise_perfect_memento_is_refused_for_a_falsified_claim():
    """Fresh, complete and session-matched — and still wrong where it matters."""
    usable, reason = _verify( ROW_INSTANCE_2, repo_root="/repo", merge_claim_fn=lambda t, r: "refuted!" )
    assert usable is False
    assert reason == "refuted!"


def test_a_memento_with_no_refutable_claim_still_verifies():

    usable, reason = _verify( "all green", repo_root="/repo", merge_claim_fn=lambda t, r: None )
    assert usable is True


def test_the_gate_defaults_to_the_real_checker( repo ):
    """
    `merge_claim_fn=None` must resolve to the REAL checker. Asserted against a
    real repo with a real merged commit — an unknown sha cannot tell the real
    checker apart from a no-op, and this test passed with a no-op substituted in
    until it was pointed at something the checker could actually refute.
    """
    body           = "`" + repo[ "merged" ][ :8 ] + "` is the only thing waiting on you"
    usable, reason = _verify( body, repo_root=repo[ "root" ] )
    assert usable is False
    assert repo[ "merged" ][ :8 ] in reason


def test_the_default_checker_allows_a_claim_that_still_stands( repo ):
    """The same path, same repo, on a commit genuinely not in HEAD."""
    body      = "`" + repo[ "unmerged" ][ :8 ] + "` is the only thing waiting on you"
    usable, _ = _verify( body, repo_root=repo[ "root" ] )
    assert usable is True


def test_the_gate_runs_after_freshness_not_before():
    """A stale memento reports STALENESS — the reader must see the first failure."""
    old            = datetime.datetime.fromisoformat( "2026-08-25T09:00:00+00:00" )
    text           = _memento( ROW_INSTANCE_2 )
    usable, reason = verify_seat_memento(
        "/slot", "abcd1234", old, read_text_fn=lambda p: text,
        repo_root="/repo", merge_claim_fn=lambda t, r: "refuted!"
    )
    assert usable is False
    assert "stale" in reason
