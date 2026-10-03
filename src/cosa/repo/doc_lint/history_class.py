"""
The history class of the claim check (row 9d40b2af).

A claim taken from OLD docstring text that is only history does not count as lost when the new
text leaves it out. The class is the "may go" column of planning-is-prompting
workflow/docstring-content.md section 2 (commit 7fb35af): dates; row, ticket, commit and session
ids; provenance; incident figures and one-off measurements; historical narrative, including the
story of a rejected alternative. A dropped reason or behaviour still counts as lost.

Where it is applied: a POST-FILTER on claims the judge already called absent. Not the extractor
(its prompt version would change and every ledgered extraction would be invalid), not the judge
(same, and a model would decide what to excuse). The filter is plain Python over the claim text and
its quote, so no ledger key moves and no model call is made. It can only turn an absent claim into
an excused one, and it is tuned to excuse too little: a claim is excused only when a history marker
matches and no reason or behaviour marker does. Anything uncertain stays lost, the harness's usual
fail-closed side. Judgement kinds with no reliable surface (provenance told in plain words,
rejected-alternative stories) are caught only by the phrases below; the rest stay lost and are the
reviewer's to read.

Honest origin: this class was defined AFTER the pilot's 523 losses were seen, by an author who did not
open them. Freeze it by the sha of this file (HISTORY_CLASS_VERSION) before any pilot re-run.
"""

import hashlib
import inspect
import re
import sys

# A history marker names the kind of history it found. The phrase "no longer" and the word
# "unchanged" are left out on purpose: each also states present behaviour ("the lock is no longer held").
HISTORY_MARKERS = (
    ( "date",        re.compile( r"\b\d{4}[-./]\d{2}[-./]\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}(?:st|nd|rd|th)?,? \d{4}\b|\bUPDATE:|\b(?:fixed|added|changed|removed|measured|ruled) (?:on |in )?(?:19|20)\d{2}\b", re.IGNORECASE ) ),
    ( "id",          re.compile( r"\b(?:row|task|bug|ticket|decision|job|pr|issue|commit|session)\s+#?[0-9a-f]{6,40}\b|\b(?:row|task|bug|ticket|decision|job|pr|issue)\s+#?\d+\b|(?<![\w-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w-])", re.IGNORECASE ) ),
    ( "provenance",  re.compile( r"\b(?:ruled|ruling|found by|reported by|noticed by|decided by|requested by|asked by|raised by|according to)\b", re.IGNORECASE ) ),
    ( "incident",    re.compile( r"\bincident\b|\bpost-?mortem\b|\bwas measured\b|\bmeasured (?:on|in|at|once)\b|\b(?:took|ran in) [\d.]+ ?(?:ms|s|sec|secs|seconds?|minutes?|hours?)\b|\b\d+ (?:of|out of) \d+ (?:were |was )?(?:correct|wrong|failed|passed)\b", re.IGNORECASE ) ),
    ( "narrative",   re.compile( r"\bwas previously\b|\bwere previously\b|\bused to\b|\bformerly\b|\boriginally\b|\bearlier (?:text|version|draft)\b|\bwas (?:changed|renamed|moved|rewritten|rejected)\b|\bwould have been the obvious\b|\brejected alternative\b|\bthe obvious (?:move|fix|choice)\b", re.IGNORECASE ) ),
)

# A reason or behaviour marker. A claim that matches any of these states something that is still true
# of the code, so it is never excused: "where they meet, keep the reason, drop the story".
REASON_MARKERS = re.compile(
    r"\bbecause\b|\bso that\b|\bso (?:a|an|the|both|every|each|it|they|that)\b|\bin order to\b|\bto (?:avoid|prevent|keep|ensure|guarantee|stop)\b"
    r"|\bmust\b|\bmay not\b|\bmust not\b|\bcannot\b|\bnever\b|\balways\b|\bonly (?:when|if)\b|\bunless\b|\botherwise\b"
    r"|\brequires?\b|\braises?\b|\bensures?\b|\breturns?\b|\brefus(?:e|es)\b|\brejects?\b|\bshould\b"
    r"|\bis (?:computed|checked|enforced|stored|validated)\b|\bare (?:computed|checked|enforced|stored|validated)\b",
    re.IGNORECASE )

HISTORY_CLASS_VERSION = "history-" + hashlib.sha256( inspect.getsource( sys.modules[ __name__ ] ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def history_kinds( claim_text, quote ):
    """
    Name the history kinds a claim matches, or none when it states a reason or behaviour.

    Requires:
        - claim_text and quote are str; quote may be empty

    Ensures:
        - returns a list of kind names from HISTORY_MARKERS, in marker order
        - returns [] when any REASON_MARKERS match in the claim text or its quote, whatever history
          markers also match
        - returns [] when no history marker matches either text
    """
    both = ( claim_text, quote )
    if any( REASON_MARKERS.search( text ) for text in both ): return []
    return [ kind for kind, pattern in HISTORY_MARKERS if any( pattern.search( text ) for text in both ) ]


def is_history( claim_text, quote ):
    """Say whether a claim is only history, so its absence from the new text is not a loss."""
    return bool( history_kinds( claim_text, quote ) )


def split_absent( claims, absent_flags ):
    """
    Split the claims judged dropped into lost and excused-as-history.

    Requires:
        - claims is a list of objects with .text and .quote (extractor Claims) or ledger dicts with "text" and "quote"
        - absent_flags has one bool per claim: True when the judge called it dropped

    Ensures:
        - returns ( lost, excused ): lost holds the indexes of dropped claims that are not history,
          excused holds ( index, kinds ) for dropped claims that are
        - a claim not judged dropped is in neither list
        - the two lists together are exactly the dropped claims, so nothing is lost by the split

    Raises:
        - ValueError when the two lists differ in length
    """
    if len( claims ) != len( absent_flags ): raise ValueError( f"{len( claims )} claims but {len( absent_flags )} flags" )
    lost    = []
    excused = []
    for i, ( claim, absent ) in enumerate( zip( claims, absent_flags ) ):
        if not absent: continue
        text, quote = ( claim[ "text" ], claim[ "quote" ] ) if isinstance( claim, dict ) else ( claim.text, claim.quote )
        kinds = history_kinds( text, quote )
        if kinds: excused.append( ( i, kinds ) )
        else:     lost.append( i )
    return lost, excused
