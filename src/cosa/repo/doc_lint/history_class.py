"""
The history class of the claim check: a tag, never an excuse.

A claim taken from the old docstring that looks like history is tagged. The class is the "may go"
column of planning-is-prompting workflow/docstring-content.md section 2. It covers dates; row, ticket, commit
and session ids; provenance; incident figures and one-off measurements; historical narrative,
including the story of a rejected alternative.

The tag changes no count. Every claim the judge calls absent is still lost. The report lists the
tagged ones apart, with a count, so a person can read them and decide. No claim is excused here.

It is a post-filter on claims the judge already called absent. It is not part of the extractor or the
judge, because a change to either prompt would void every ledgered verdict. The filter is plain Python,
so no ledger key moves and no model is called.

A claim is tagged when its claim text carries a history marker. The quote is never searched for
history. It is a stretch of the old docstring and often ends in a citation or a date that the claim
does not state. What else the claim says does not matter, because a tag excuses nothing and the
reader sees every tagged claim in the report. Any reason or behaviour marker in the claim text or in
its quote keeps a claim untagged.

Provenance tags only with a named person ("Rick ruled") or alongside a date or an id. The words
"ruled", "ruling" and "according to" tag nothing alone. The words "no longer" and "unchanged" are
not markers, because each also states present behaviour.

The class was defined after the pilot's losses were seen, by an author who did not open them.
HISTORY_CLASS_VERSION is the hash of this file, so freeze the class by recording it before any re-run.
"""

import hashlib
import inspect
import re
import sys

_UNITS = r"(?:ms|s|sec|secs|seconds?|minutes?|hours?)"

# A history marker names the kind of history it found.
HISTORY_MARKERS = (
    ( "date",       re.compile( r"\b\d{4}[-./]\d{2}[-./]\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}(?:st|nd|rd|th)?,? \d{4}\b|\bUPDATE:|\b(?:fixed|added|changed|removed|measured|ruled) (?:on |in )?(?:19|20)\d{2}\b(?![-./]\d)", re.IGNORECASE ) ),
    ( "id",         re.compile( r"\b(?:row|task|bug|ticket|decision|job|pr|issue|commit|session)\s+#?[0-9a-f]{6,40}\b|\b(?:row|task|bug|ticket|decision|job|pr|issue)\s+#?\d+\b|(?<![\w-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w-])", re.IGNORECASE ) ),
    # Case-sensitive on purpose: a person is a capitalised name. Bare "ruled", "ruling" and "according to" are not markers.
    ( "provenance", re.compile( r"\b[A-Z][a-z]+ (?:ruled|decided|found|reported|noticed|requested|asked|raised)\b|\b(?:found|reported|noticed|decided|requested|asked|raised) by [A-Za-z]+\b" ) ),
    ( "incident",   re.compile( rf"\bincident\b|\bpost-?mortem\b|\b(?:was|were) measured\b|\bmeasured (?:on|in|at|once)\b|(?:\b(?:the|a|an)\s+)?(?:\w+\s+){{0,2}}?\b(?:took|ran in) [\d.]+ ?{_UNITS}\b|\b\d+ (?:of|out of) \d+ (?:were |was )?(?:correct|wrong|failed|passed)\b", re.IGNORECASE ) ),
    ( "narrative",  re.compile( r"\b(?:was|were) previously\b|\bused to\b|\bformerly\b|\boriginally\b|\bearlier (?:text|version|draft)\b|\b(?:was|were) (?:changed|renamed|moved|rewritten|rejected)\b|\bwould have been the obvious\b|\brejected alternative\b|\bthe obvious (?:move|fix|choice)\b", re.IGNORECASE ) ),
)

# A reason or behaviour marker. A claim that matches any of these in its text or its quote states something
# that is still true of the code, so it is never tagged: where they meet, keep the reason, drop the story.
REASON_MARKERS = re.compile(
    r"\bbecause\b|\bso that\b|\bso (?:a|an|the|both|every|each|it|they|that)\b|\bin order to\b|\bto (?:avoid|prevent|keep|ensure|guarantee|stop)\b"
    r"|\bmust\b|\bmay not\b|\bmust not\b|\bcannot\b|\bnever\b|\balways\b|\bonly (?:when|if)\b|\bunless\b|\botherwise\b"
    r"|\brequires?\b|\braises?\b|\bensures?\b|\breturns?\b|\brefus(?:e|es)\b|\brejects?\b|\bshould\b"
    r"|\bis (?:computed|checked|enforced|stored|validated)\b|\bare (?:computed|checked|enforced|stored|validated)\b",
    re.IGNORECASE )

HISTORY_CLASS_VERSION = "history-" + hashlib.sha256( inspect.getsource( sys.modules[ __name__ ] ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def history_kinds( claim_text, quote ):
    """
    Name the history kinds a claim is tagged with, or none.

    Requires:
        - claim_text and quote are str; quote may be empty

    Ensures:
        - returns [] when a reason or behaviour marker matches the claim text or its quote
        - history markers are searched in claim_text only, never in the quote
        - returns [] when no history marker matches the claim text
        - otherwise returns the matched kind names in marker order
    """
    if REASON_MARKERS.search( claim_text ) or REASON_MARKERS.search( quote ): return []
    return [ kind for kind, pattern in HISTORY_MARKERS if pattern.search( claim_text ) ]


def is_history( claim_text, quote ):
    """Say whether a claim is tagged as history. The tag excuses nothing."""
    return bool( history_kinds( claim_text, quote ) )


def tag_absent( claims, absent_flags ):
    """
    List the claims judged dropped, and say which of them are tagged as history.

    Requires:
        - claims is a list of objects with .text and .quote (extractor Claims) or ledger dicts with "text" and "quote"
        - absent_flags has one bool per claim: True when the judge called it dropped

    Ensures:
        - returns ( dropped, tagged ): dropped holds the indexes of every claim judged dropped, tagged or not;
          tagged holds ( index, kinds ) for those of them that look like history
        - tagged is a subset of dropped, and no dropped claim is left out: nothing is excused
        - a claim not judged dropped is in neither list

    Raises:
        - ValueError when the two lists differ in length
    """
    if len( claims ) != len( absent_flags ): raise ValueError( f"{len( claims )} claims but {len( absent_flags )} flags" )
    dropped = []
    tagged  = []
    for i, ( claim, absent ) in enumerate( zip( claims, absent_flags ) ):
        if not absent: continue
        dropped.append( i )
        text, quote = ( claim[ "text" ], claim[ "quote" ] ) if isinstance( claim, dict ) else ( claim.text, claim.quote )
        kinds = history_kinds( text, quote )
        if kinds: tagged.append( ( i, kinds ) )
    return dropped, tagged
