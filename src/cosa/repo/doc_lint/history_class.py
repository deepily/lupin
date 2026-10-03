"""
The history class of the claim check.

A claim taken from the old docstring that is only history does not count as lost when the new text
leaves it out. The class is the "may go" column of planning-is-prompting workflow/docstring-content.md
section 2: dates; row, ticket, commit and session ids; provenance; incident figures and one-off
measurements; historical narrative, including the story of a rejected alternative.
A dropped reason or behaviour still counts as lost.

It is a post-filter on claims the judge already called absent. It is not part of the extractor or the
judge, because a change to either prompt would void every ledgered verdict, and a model would then
decide what to excuse. The filter is plain Python, so no ledger key moves and no model is called.

The filter is an upper bound on excusing, and a person reads every excused claim: the report lists
each one with its quote. Two tests must both pass before a claim is excused.
    1. History is found in the claim text. The quote is never searched for history: it is a stretch
       of the old docstring and often ends in a citation or a date that the claim does not state.
    2. Nothing but history is left. The history spans are cut out of the claim text, and every word
       that remains must be a word of history vocabulary or a function word (HISTORY_GLUE). Any
       other word is read as a statement of what the code does, so the claim counts as lost.
Any reason or behaviour marker in the claim text or in its quote also keeps the claim lost.

Provenance counts only with a named person ("Rick ruled") or alongside a date or an id. The words
"ruled", "ruling" and "according to" excuse nothing alone. The words "no longer" and "unchanged" are
not markers, because each also states present behaviour.

The class was defined after the pilot's losses were seen, by an author who did not open them.
HISTORY_CLASS_VERSION is the hash of this file, so freeze the class by recording it before any re-run.
"""

import hashlib
import inspect
import re
import sys

_UNITS = r"(?:ms|s|sec|secs|seconds?|minutes?|hours?)"

# A history marker names the kind of history it found. Every match is a span that the residue test cuts out.
HISTORY_MARKERS = (
    ( "date",       re.compile( r"\b\d{4}[-./]\d{2}[-./]\d{2}\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}(?:st|nd|rd|th)?,? \d{4}\b|\bUPDATE:|\b(?:fixed|added|changed|removed|measured|ruled) (?:on |in )?(?:19|20)\d{2}\b(?![-./]\d)", re.IGNORECASE ) ),
    ( "id",         re.compile( r"\b(?:row|task|bug|ticket|decision|job|pr|issue|commit|session)\s+#?[0-9a-f]{6,40}\b|\b(?:row|task|bug|ticket|decision|job|pr|issue)\s+#?\d+\b|(?<![\w-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w-])", re.IGNORECASE ) ),
    # Case-sensitive on purpose: a person is a capitalised name. Bare "ruled", "ruling" and "according to" are not markers.
    ( "provenance", re.compile( r"\b[A-Z][a-z]+ (?:ruled|decided|found|reported|noticed|requested|asked|raised)\b|\b(?:found|reported|noticed|decided|requested|asked|raised) by [A-Za-z]+\b" ) ),
    ( "incident",   re.compile( rf"\bincident\b|\bpost-?mortem\b|\b(?:was|were) measured\b|\bmeasured (?:on|in|at|once)\b|(?:\b(?:the|a|an)\s+)?(?:\w+\s+){{0,2}}?\b(?:took|ran in) [\d.]+ ?{_UNITS}\b|\b\d+ (?:of|out of) \d+ (?:were |was )?(?:correct|wrong|failed|passed)\b", re.IGNORECASE ) ),
    ( "narrative",  re.compile( r"\b(?:was|were) previously\b|\bused to\b|\bformerly\b|\boriginally\b|\bearlier (?:text|version|draft)\b|\b(?:was|were) (?:changed|renamed|moved|rewritten|rejected)\b|\bwould have been the obvious\b|\brejected alternative\b|\bthe obvious (?:move|fix|choice)\b", re.IGNORECASE ) ),
)

# What may be left of a claim once its history spans are cut out: function words and the vocabulary of
# history itself. Every other word, and every bare number, is read as a statement about the code.
HISTORY_GLUE = frozenset( (
    "a an the of to in on at by for and or is are was were be been it its that this these those with from as after before when then also which who"
    " row task bug ticket decision job pr issue commit session sha ruled ruling decided found reported noticed requested asked raised"
    " fixed added changed removed renamed moved rewritten rejected introduced reverted merged landed measured incident previously formerly"
    " originally earlier text version draft update updated see per" ).split() )

# A reason or behaviour marker. A claim that matches any of these in its text or its quote states something
# that is still true of the code, so it is never excused: where they meet, keep the reason, drop the story.
REASON_MARKERS = re.compile(
    r"\bbecause\b|\bso that\b|\bso (?:a|an|the|both|every|each|it|they|that)\b|\bin order to\b|\bto (?:avoid|prevent|keep|ensure|guarantee|stop)\b"
    r"|\bmust\b|\bmay not\b|\bmust not\b|\bcannot\b|\bnever\b|\balways\b|\bonly (?:when|if)\b|\bunless\b|\botherwise\b"
    r"|\brequires?\b|\braises?\b|\bensures?\b|\breturns?\b|\brefus(?:e|es)\b|\brejects?\b|\bshould\b"
    r"|\bis (?:computed|checked|enforced|stored|validated)\b|\bare (?:computed|checked|enforced|stored|validated)\b",
    re.IGNORECASE )

_WORD = re.compile( r"[A-Za-z][A-Za-z'-]*|\d+" )

HISTORY_CLASS_VERSION = "history-" + hashlib.sha256( inspect.getsource( sys.modules[ __name__ ] ).encode( "utf-8" ) ).hexdigest()[ :10 ]


def history_kinds( claim_text, quote ):
    """
    Name the history kinds of a claim that is only history, or none.

    Requires:
        - claim_text and quote are str; quote may be empty

    Ensures:
        - returns [] when a reason or behaviour marker matches the claim text or its quote
        - history markers are searched in claim_text only, never in the quote
        - returns [] when no history marker matches the claim text
        - returns [] when, with every history span cut out of claim_text, any word is outside HISTORY_GLUE
          or any bare number remains: a statement about the code is left, so the claim is lost
        - otherwise returns the matched kind names in marker order
    """
    if REASON_MARKERS.search( claim_text ) or REASON_MARKERS.search( quote ): return []
    kinds = []
    cut   = [ False ] * len( claim_text )
    for kind, pattern in HISTORY_MARKERS:
        found = list( pattern.finditer( claim_text ) )
        if found: kinds.append( kind )
        for match in found: cut[ match.start():match.end() ] = [ True ] * ( match.end() - match.start() )
    if not kinds: return []
    left = "".join( " " if gone else char for char, gone in zip( claim_text, cut ) )
    if any( word.lower() not in HISTORY_GLUE for word in _WORD.findall( left ) ): return []
    return kinds


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
        - returns ( lost, excused ); lost holds the indexes of dropped claims that are not history,
          excused holds ( index, kinds ) for dropped claims that are
        - a claim not judged dropped is in neither list
        - the two lists together cover every dropped claim, so the split drops none

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
