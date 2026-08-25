"""
Merge-claim check — the ONE slot a memento reliably gets wrong (row 0c80f26d).

THE SHAPE, measured three times in one evening across two workers: every stale
line was a claim about SOMEBODY ELSE'S PENDING ACTION. A worker writes "three
commits are unpushed and unmerged" at the moment they stop working; the manager
merges within minutes; the line is false almost immediately and the worker is no
longer running to notice. The memento is accurate about everything its author
controls and wrong about the one thing they do not.

⇒ WHY THIS SLOT AND NOT ANY OTHER STALE LINE: it is the line a successor ACTS on
first. "There is unmerged work" sends them hunting for it, or worse, re-landing
it. Every other stale line costs a re-read; this one costs a wrong action.

WHAT THIS CHECKS: a claim the REPO can prove false — a negative merge claim
naming a commit that is ALREADY an ancestor of HEAD. git decides, not a guess
about intent, so there is no false-positive class to argue about.

⚠️ IT DOES NOT CATCH A CLAIM WITH NO SHA, AND THAT IS TWO OF THE ROW'S THREE
INSTANCES ("three commits are unpushed and unmerged", "the seven commits are
yours to merge"). Nothing in the text names a commit, so nothing can be resolved
and nothing can be refuted. That gap is real and is NOT closed here; it is closed
by john's template rule — carry the BRANCH NAME plus `git log HEAD..<branch>`
rather than a claim — which is a fleet-template change and Rick's call, not this
module's. Stated because a detector whose limits are unwritten gets read as
covering everything.

MEASURED AGAINST THE REAL CORPUS, 469 mementos in io/mementos:
  · a blunt claim-SHAPE gate (any "unmerged"/"waiting on you" line with no live
    query) flags 18 lines, of which about 4 are the trap — roughly 30% precision.
    That is why this module does not do that; a certification gate at ~30%
    precision gets switched off within a day.
  · this check — tight coupling plus a resolvable sha — matches 6 lines. Two are
    krishna's CORRECT pattern (`git log 8657cfa9..HEAD` -> empty), excluded by
    the live-query rule below, and the remaining 3 are genuinely stale claims
    whose branch was merged after the memento was written.

SAFETY — this runs on the reap path, where a raise would strand a seat:
  - FAIL-OPEN on infrastructure: an unresolvable sha, a git error, a missing repo
    all mean "cannot refute", which is ALLOW. Only a POSITIVE refutation refuses.
  - The git probe is INJECTED, so tests never touch a real repo.
"""
import re
import subprocess
from typing import Callable, List, Optional, Tuple


# A NEGATIVE claim about merge state — the assertion that work is still pending
# on somebody else. Positive receipts ("merged at <sha>") are durable and are not
# matched here: they will be true forever.
_NEGATIVE_CLAIM = (
    r"(?:unmerged|un-merged|not\s+yet\s+merged|yours?\s+to\s+merge|"
    r"to\s+merge\s+whenever|waiting\s+(?:on|for)\s+you|awaiting\s+(?:your\s+)?merge|"
    r"needs?\s+merging|pending\s+merge|only\s+thing\s+waiting)"
)

# An abbreviated or full commit sha.
_SHA = r"[0-9a-f]{7,40}"

# The claim and the sha must sit in the SAME CLAUSE. Loosening this to "somewhere
# on the line" is what took the corpus match count from 6 to 124 — prose that
# DESCRIBES merges that happened is full of shas that are correctly ancestors,
# and every one of those would have been a false refusal.
_COUPLED_RE = re.compile(
    r"(?i)(?:`?(?P<before>" + _SHA + r")`?[^\n]{0,48}?" + _NEGATIVE_CLAIM +
    r"|" + _NEGATIVE_CLAIM + r"[^\n]{0,48}?`?(?P<after>" + _SHA + r")`?)"
)

# A line that SHOWS ITS WORK is the pattern we want more of, not less — it names
# the command and its reading, so a successor can see how old the reading is.
# "`git log 8657cfa9..HEAD` -> empty, nothing unmerged" must never be refused for
# containing both a sha and the word "unmerged".
_LIVE_QUERY_RE = re.compile( r"git\s+log\s+\S*\.\.|git\s+merge-base|git\s+branch\s+--merged|task_query" )


def default_ancestry_probe( sha: str, repo_root: str ) -> Optional[ bool ]:
    """
    Ask git whether `sha` is already an ancestor of HEAD.

    Requires:
        - sha is a 7-40 char hex string
        - repo_root is a path inside the repository to ask

    Ensures:
        - True when the commit exists AND is an ancestor of HEAD
        - False when the commit exists and is NOT an ancestor
        - None when the commit is unknown, or git cannot answer at all — the
          "cannot refute" verdict, which the caller treats as allow
        - never raises
    """
    try:
        exists = subprocess.run(
            [ "git", "-C", repo_root, "cat-file", "-e", sha + "^{commit}" ],
            capture_output=True, timeout=10
        )
        if exists.returncode != 0:
            return None
        merged = subprocess.run(
            [ "git", "-C", repo_root, "merge-base", "--is-ancestor", sha, "HEAD" ],
            capture_output=True, timeout=10
        )
        return merged.returncode == 0
    except ( OSError, subprocess.SubprocessError ):
        return None


def find_merge_claims( text: str ) -> List[ Tuple[ int, str, str ] ]:
    """
    Every negative merge claim in `text` that names a commit in the same clause.

    Requires:
        - text is the memento's content

    Ensures:
        - returns ( line_number, sha, line ) per coupled claim, 1-indexed
        - SKIPS a line carrying a live query — showing the command and its
          reading is the pattern being encouraged, not the one being caught
        - returns [] for text with no such claim
    """
    found = []
    for number, line in enumerate( text.split( "\n" ), 1 ):
        if _LIVE_QUERY_RE.search( line ):
            continue
        for match in _COUPLED_RE.finditer( line ):
            sha = match.group( "before" ) or match.group( "after" )
            found.append( ( number, sha, line.strip() ) )
    return found


def refuted_merge_claim(
    text,
    repo_root,
    *,
    ancestry_probe : Optional[ Callable ] = None,
) -> Optional[ str ]:
    """
    The first merge claim the repo PROVES false, or None when none can be refuted.

    Requires:
        - text is the memento's content (str); a non-str is treated as no claim
        - repo_root is a path inside the repository to ask
        - ancestry_probe is None (real git) or injected for testing

    Ensures:
        - returns a reason naming the line number, the sha and the offending line
          ONLY when the probe answers True — the commit is already in HEAD, so the
          claim that it is unmerged is false AS OF NOW
        - returns None when the probe answers False (claim still true) or None
          (cannot resolve) — an unresolvable sha never refuses a memento
        - FAIL-OPEN: any unexpected error → None
    """
    try:
        if not isinstance( text, str ) or not text:
            return None
        probe = ancestry_probe if ancestry_probe is not None else default_ancestry_probe
        for number, sha, line in find_merge_claims( text ):
            if probe( sha, repo_root ) is True:
                return (
                    "memento line " + str( number ) + " claims work is still unmerged, and the "
                    "repo says otherwise: " + sha + " is ALREADY an ancestor of HEAD. Offending "
                    "line: " + repr( line ) + ". This is the one line a successor acts on first — "
                    "a false 'there is unmerged work' sends them hunting for it, or re-landing it. "
                    "Write the BRANCH NAME and the command instead of the claim: "
                    "`git log HEAD..<branch>`. A pointer to a live check cannot go stale; a claim "
                    "about somebody else's pending action goes stale the moment they act."
                )
        return None
    except Exception:                    # pragma: no cover - fail-open backstop: every statement above is total over the validated inputs, so no input reaches it; kept because a reap-path check must never strand a seat
        return None
