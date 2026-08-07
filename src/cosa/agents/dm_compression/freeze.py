"""
The freeze protocol — extract, placehold, validate, restore.

Nothing here calls a model. The whole point of this module is that it can be
exercised at corpus scale for free, and that it is what makes the model call in
phase 2 safe.

The claim this module makes, stated exactly (expert review, 2026-08-06):

    Exact preservation of selected byte spans through a lossy rewrite.

It does NOT claim the rewrite preserved meaning. A placeholder can survive
perfectly and end up attached to the wrong claim; that failure is called
relocation, it passes every structural check here, and catching it is a
separate layer's job.
"""

import hashlib
import re

from dataclasses import dataclass, field


# ──────────────────────────────────────────────────────────────────────────────
# Span taxonomy
#
# Ordering in this list IS the precedence order used to break ties when two
# candidate spans are the same length. Earlier = wins.
#
# The taxonomy is deliberately wider than the plan's original ten classes. The
# expert review named a list of classes the corpus would never surface on its
# own (§2), because the corpus can only ground-truth what the regexes already
# catch. Those are folded in here.
# ──────────────────────────────────────────────────────────────────────────────

# A literal must never be *partially* frozen, so every pattern below is written
# to match a whole token. Where a pattern could match a prefix of a longer
# token, it carries an explicit boundary guard rather than relying on \b, which
# does not do what people expect next to punctuation.

# One emoji or symbol, with any skin-tone modifier, variation selector, keycap
# or zero-width joiner that belongs to it, repeated.
_GLYPH_RUN = (
    "(?:[\U0001F000-\U0001FAFF☀-➿⬀-⯿←-⇿]"
    "[\U0001F3FB-\U0001F3FF️⃣]*(?:‍)?)+"
)

_PATTERNS = [

    # ─── HARD: exact references. Corrupting one of these corrupts an action. ──

    # Fenced code first and longest — everything inside is opaque by definition.
    ( "FENCE",    "HARD", re.compile( r"```.*?```", re.DOTALL ) ),
    ( "CODE",     "HARD", re.compile( r"`[^`\n]+`" ) ),

    ( "URL",      "HARD", re.compile( r"\bhttps?://[^\s<>()\[\]{}\"'⟦⟧]+" ) ),
    ( "EMAIL",    "HARD", re.compile( r"\b[\w.+-]+@[\w-]+\.[\w.-]*[\w]\b" ) ),

    # "POST /api/presentation-generator/submit" is ONE reference. Split into a
    # verb and a path, the verb becomes compressible prose and a rewriter can
    # turn a POST into a GET.
    ( "ROUTE",    "HARD", re.compile( r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/[\w/{}.:-]*" ) ),
    # Docker mount specs: "./io:/var/lupin/io". The colon reads as path-then-port
    # to two different patterns, so it must win as a single span.
    ( "MOUNT",    "HARD", re.compile( r"(?<![\w:])\.{0,2}/[\w./-]+:/[\w./-]+" ) ),

    ( "WINPATH",  "HARD", re.compile( r"\b[A-Za-z]:\\[^\s\"'⟦⟧]+" ) ),
    # file.py:123 and every shape the corpus actually uses: ranges
    # (job.py:249-256, en-dash included), comma lists (job.py:58,106,249),
    # mixtures (orchestrator.py:1441,1456-1459), and line:col (file.py:12:34).
    #
    # The tail matters more than it looks. Match only the first number and
    # `job.py:58,106,249` freezes as `job.py:58` while `,106,249` travels on as
    # ordinary prose for the rewriter to drop. What gets delivered is a
    # confident, valid-looking citation pointing at fewer sites than the author
    # named — and it passes every structural check in this module, because
    # structurally nothing went wrong.
    #
    # Both shapes found by María against the corpus: ranges in the labeled
    # sample, comma lists in a follow-up sweep (11 live instances, 0 of 635
    # spans left uncovered by this pattern). 2026-08-07.
    # ⚠️ The closing guard is `(?!\w)(?!\.\d)`, NOT `(?![\w.])`.
    #
    # `(?![\w.])` was there to stop `file.py:12.5` matching as `file.py:12`, and
    # it did — while also refusing to match at all when a citation ends a
    # sentence. `judge.py:572.` matched nothing, and `judge.py:249-256.` matched
    # `judge.py:249`, silently reintroducing the truncation bug this pattern was
    # widened to fix. 21 of 647 corpus citations end in a period.
    ( "FILELINE", "HARD", re.compile(
        r"\b[\w./-]+\.\w{1,6}:\d+(?:[-–]\d+)?(?:,\d+(?:[-–]\d+)?)*(?::\d+)?(?!\w)(?!\.\d)"
    ) ),
    # Absolute-ish, or relative with a real extension. Deliberately NOT a bare
    # "a/b" — that matches "and/or" and every slash in prose.
    ( "PATH",     "HARD", re.compile( r"(?:/[\w.-]+){2,}/?|\b(?:[\w.-]+/)+[\w-]+\.\w{1,6}\b" ) ),
    # A bare filename with no directory. The PATH pattern needs a slash, so
    # "test_dm_verbs.py" was travelling unprotected.
    ( "FILENAME", "HARD", re.compile(
        r"\b[\w-]+\.(?:py|js|ts|tsx|jsx|md|json|jsonl|ya?ml|ini|cfg|toml|sh|sql"
        r"|html|css|txt|log|csv|png|jpe?g|svg|webp|gif)\b"
    ) ),

    ( "UUID",     "HARD", re.compile( r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b" ) ),
    # Git shas and 8-hex session ids.
    #
    # Requires a hex LETTER so that a bare run of digits is read as a number
    # rather than a sha. Deliberately does NOT also require a digit: María
    # measured the all-letter false-positive risk across all 2,951 bodies and
    # found exactly one hit, itself a real hex string. A digit guard would cost
    # recall on all-letter shas to buy nothing.
    ( "SHA",      "HARD", re.compile( r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b" ) ),

    ( "IP",       "HARD", re.compile( r"\b(?:\d{1,3}\.){3}\d{1,3}\b" ) ),
    ( "ISOTS",    "HARD", re.compile( r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?" ) ),
    ( "ISODATE",  "HARD", re.compile( r"\b\d{4}[-.]\d{2}[-.]\d{2}\b" ) ),
    ( "SEMVER",   "HARD", re.compile( r"\bv?\d+\.\d+\.\d+(?:[-+][\w.]+)?\b" ) ),

    # ⚠️ This pattern also fires on LINE NUMBERS (":27", ":974"). That is
    # harmless while placeholders stay opaque, but it means the type label on a
    # placeholder is NOT trustworthy. Nothing downstream may reason from a
    # placeholder's kind — see the note on validate(). María, 2026-08-07.
    ( "PORT", "VERIFY", re.compile( r"(?<![\w.:]):\d{2,5}\b" ) ),
    ( "ISSUE", "VERIFY", re.compile( r"#\d+\b|\b[A-Z][A-Z0-9]{1,9}-\d+\b" ) ),
    # Section and gate pointers. Pure references: renumbering one breaks the
    # citation while leaving the sentence perfectly readable.
    #
    # ⚠️ The gate alternative MUST anchor its label. Written as
    # `[Gg]ate\s+\(?[A-Za-z0-9]\)?` it swallows the first letter of the next
    # word — "gate the" froze as "gate t" — which produced 1,307 junk spans and
    # was the largest single contributor to over-freezing.
    ( "SECTION", "VERIFY", re.compile(
        r"§\s?[\w.]+|\b[Gg]ate\s+(?:\([A-Za-z0-9]\)|[A-Za-z0-9]\b)|\b[Ii]tem\s+\d+\b"
    ) ),
    # Flags carry their value: --autoplay-policy=no-user-gesture-required is
    # one span, not a flag followed by compressible prose.
    ( "FLAG",     "HARD", re.compile( r"(?<![\w-])--?[A-Za-z][\w-]*(?:=(?:\"[^\"\n]*\"|[^\s,;)]+))?" ) ),
    # key=value config pairs. The value IS the claim; freezing only a quoted
    # half would leave the key rewritable.
    ( "KEYVAL",   "HARD", re.compile( r"\b[A-Za-z_][\w.]*=(?:\"[^\"\n]*\"|'[^'\n]*'|[^\s,;)]+)" ) ),
    # UPPER_SNAKE only. Bare all-caps words like CRITICAL are prose, not names.
    ( "CONST",    "HARD", re.compile( r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b" ) ),
    # Dotted calls and snake_case identifiers: cu.get_project_root(),
    # _CoreHarness.setUp, _slide_budget. The CONST pattern only sees the
    # SCREAMING ones.
    ( "IDENT",    "HARD", re.compile(
        r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+(?:\(\))?"
        r"|\b_?[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"
    ) ),
    # Deltas, signed values and ratios. Arrows, the Unicode minus and the
    # "n-of-m" form all defeat plain word-boundary numeric patterns.
    # The en/em-dash alternatives matter on their own: "lines 486–703" carries
    # a range with no filename attached, so FILELINE never sees it and without
    # this it freezes as two unrelated numbers with a compressible dash between
    # them. Same silent-truncation shape as the file:line ranges.
    ( "DELTA", "VERIFY", re.compile(
        r"\d+(?:\.\d+)?\s?(?:->|=>|[→↔⇒–—-])\s?\d+(?:\.\d+)?"
        r"|[±−+]\s?\d+(?:\.\d+)?"
        r"|\b\d+[- ]of[- ]\d+\b"
    ) ),
    # High-entropy runs: tokens, keys, base64 blobs. Anything this long and
    # this dense is not something a rewriter should be retyping.
    ( "SECRET",   "HARD", re.compile( r"\b[A-Za-z0-9_\-]{32,}\b" ) ),
    # Persona glyphs and emoji. These carry sender identity and acknowledgement
    # semantics in this fleet — 🫡 is a reply, not decoration — and a rewriter
    # told to strip ornament will erase attribution.
    # Every glyph EXCEPT the one opening the message.
    #
    # ⚠️ Line-leading glyphs belong here, not in the removable set. They read
    # like ceremony and are not: across the corpus the non-opening line-leading
    # glyphs are ⇒ 27, ⚠️ 23, → 5, ✅ 4, 🟡 3, 🔴 2 — consequence markers and
    # verdicts. Deleting a ✅ from the front of a line turns a pass into an
    # unmarked statement.
    #
    # Only the MESSAGE-opening glyph is removable, and only because the
    # envelope's `from` field already carries the sender. Nothing makes a
    # mid-body ⚠️ redundant. (María, 2026-08-07.)
    ( "GLYPH", "VERIFY", re.compile( r"(?<!\A)" + _GLYPH_RUN ) ),

    # ─── SOFT: quantities and quoted material. ───────────────────────────────
    #
    # The review pushed back hard on the plan's claim that SOFT false positives
    # are "nearly free" (§3): freezing a long quoted sentence can eat the whole
    # compression budget, and freezing a coined term preserves exactly the
    # jargon the rewriter exists to remove. Hence the length cap on QUOTE.

    # Short quoted spans only — 8 words.
    #
    # An unbounded rule freezes whole quoted sentences, which is the review's
    # issue 3 made concrete: it preserves the exact prose the rewriter exists to
    # compress. Above the cap the quote is left alone and the literals INSIDE it
    # are frozen individually, so the citation survives and the prose still
    # compresses. Cap confirmed against live examples by María, 2026-08-07.
    ( "QUOTE",    "SOFT", re.compile( r"\"[^\"\n\s]+(?:\s+[^\"\n\s]+){0,7}\"" ) ),
    ( "MONEY", "VERIFY", re.compile( r"[$€£]\s?\d+(?:[.,]\d+)*" ) ),
    ( "NUMUNIT", "VERIFY", re.compile(
        r"\b\d+(?:[.,]\d+)*\s?"
        r"(?:ms|s|sec|secs|second|seconds|min|mins|minute|minutes|hr|hrs|hour|hours"
        r"|d|day|days|wk|weeks|mo|months|%|KB|MB|GB|TB|kb|mb|gb|tb|[kKMB]|x|×)(?![\w])"
    ) ),
    # Numbers spelled as words. No digit pattern sees these, and a rewriter
    # asked to be terse will happily turn "twelve thousand two hundred forty
    # one" into "about twelve thousand" — a corrupted quantity that survives
    # every structural check. Named the worst extraction gap in María's
    # labeled-sample pass, 2026-08-07.
    #
    # Guarded against prose: a bare small number word ("one of the sessions")
    # is NOT frozen. It qualifies only as part of a multi-word sequence, or
    # when it carries a magnitude ("thousand", "million").
    ( "NUMWORD",  "SOFT", re.compile(
        r"\b(?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|"
        r"forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|trillion)"
        r"(?:[\s-]+(?:and[\s-]+)?(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
        r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|"
        r"trillion))+"
        r"|(?:hundred|thousand|million|billion|trillion))\b",
        re.IGNORECASE
    ) ),
]


# ──────────────────────────────────────────────────────────────────────────────
# The VERIFY tier — literals that must survive but cannot afford a placeholder
#
# A bare integer averages 1.06 tokens. No placeholder can beat that: freezing
# all 7,099 of them costs +655% under the plan's ⟦L00⟧, +277% under [[L00]] and
# +183% even under the cheapest bracket tested. The arithmetic does not depend
# on the format — a substitution can never be smaller than a one-token literal.
#
# They still matter. Read in context they are load-bearing: "2710 passed / 1
# skipped", "199 stmts / 0 miss", "census 31/31", "timeout = 600".
#
# So they are checked WHERE THEY STAND. No substitution, no added tokens: the
# multiset of these literals in the rewrite must equal the multiset that went
# out. That catches omission and mutation. It does NOT catch relocation —
# "3 failed / 21669 passed" with the two numbers swapped passes a multiset
# check — which is why clause confinement is the companion signal and why this
# tier is honest about being a check rather than a guarantee.
#
# María, 2026-08-07 (addendum 3).
# The tier is an ECONOMIC decision, not a judgement about importance. Every
# class below matters — losing a port or a section pointer corrupts a claim
# exactly as badly as losing a path. They sit here because their literals are
# CHEAPER than the ~3 tokens a placeholder costs, so substituting them spends
# tokens to buy protection that verifying in place provides for free.
#
# Measured mean tokens per literal (o200k), María 2026-08-07:
#   net loss   — port 2.49 · num_unit 2.28 · percent 2.25 · bare int 1.06
#   break-even — section_ptr 3.10 · ratio 3.22
#   payers     — uuid 24 · email 9.4 · quoted 7.1 · backticked 7.0 · file:line 6.0
#
# The margin this protects is thin: 5,799 tokens on 95,735, about 6%. Every
# cheap class moved into the freeze tier eats it.
_INT_PATTERN = ( "INT", re.compile( r"(?<![\w.$€£])-?\d+(?:[.,]\d+)*(?![\w.])" ) )


def _verify_patterns():
    """
    Derive the verify-tier patterns from _PATTERNS on every call.

    Deliberately NOT snapshotted into a module-level list. A snapshot is taken
    once at import, so anything that changes a pattern in _PATTERNS afterwards
    leaves the two views disagreeing — the freeze path sees the new pattern and
    the verify path keeps the old one.

    That is not hypothetical. It fooled a falsification pass: reverting the
    section-pointer fix in _PATTERNS left the verify path still holding the
    fixed pattern, the guard test kept passing, and the guard looked absent when
    it was real. A test harness that cannot reliably break the thing it is
    testing reports the wrong answer in both directions.
    """
    return [ ( kind, pattern ) for kind, tier, pattern in _PATTERNS if tier == "VERIFY" ] + [ _INT_PATTERN ]


VERIFY_KINDS = tuple(
    [ kind for kind, tier, _ in _PATTERNS if tier == "VERIFY" ] + [ _INT_PATTERN[ 0 ] ]
)


# ──────────────────────────────────────────────────────────────────────────────
# REMOVABLE BOILERPLATE — declared, not verified
#
# The one class of content the rewriter is ALLOWED to delete. This is the first
# concrete piece of the review's issue 1, the semantic-preservation contract:
# something has to say what may be dropped, or every deletion looks like damage.
#
# It exists because verifying too much is its own failure. Rick's second goal is
# stripping ceremony, and in this fleet the ceremony is largely glyphs: 58% of
# messages carry one, 1,936 occurrences, 78% of them leading and decorative —
# 🦉 574, 🫡 487, 🕊️ 141, which are persona marks and salutes. Verify those and
# the rewriter triggers fail-closed on most of the corpus BY OBEYING ITS
# INSTRUCTIONS, and the fallback rate reads as a bug when it is the system
# working. (María, 2026-08-07.)
#
# A LEADING glyph run is removable: the sender's identity is already in the
# envelope's `from` field, so it carries nothing the recipient loses. An INLINE
# glyph is not removable — mid-sentence ✅ ⚠️ ✓ are content markers, and those
# stay in the verify tier.
#
# Anything added here is a deliberate widening of what the rewriter may destroy.
# Measure before adding, and say what makes it redundant rather than merely
# decorative.
#
# ⚠️ Anchored at `\A` — the MESSAGE opening, not every line opening.
#
# This was briefly `(?m)^`, to close a gap where a line-leading glyph sat in
# neither tier. That fix was worse than the gap: it made all 68 non-opening
# line-leading glyphs deletable, and those are overwhelmingly ⇒ ⚠️ ✅ 🔴 —
# consequence markers and verdicts, not ceremony. The gap is properly closed on
# the other side, by letting GLYPH claim them for the verify tier.
#
# The narrow argument is the only one that holds: a message-opening 🦉 is
# redundant because the envelope's `from` field already names the sender.
_REMOVABLE_BOILERPLATE = [
    ( "LEADING_GLYPH", re.compile( r"\A\s*" + _GLYPH_RUN + r"\s*" ) ),
]

REMOVABLE_KINDS = tuple( kind for kind, _ in _REMOVABLE_BOILERPLATE )

HARD_KINDS = tuple( kind for kind, tier, _ in _PATTERNS if tier == "HARD" )
SOFT_KINDS = tuple( kind for kind, tier, _ in _PATTERNS if tier == "SOFT" )

_KIND_RANK = { kind: i for i, ( kind, _, _ ) in enumerate( _PATTERNS ) }

# Delimiters.
#
# ⚠️ NOT the plan's ⟦ ⟧ (U+27E6/U+27E7). Those read beautifully and cost a
# fortune: neither character is in the BPE vocabulary of any current tokenizer,
# so each one fragments into byte tokens. María benchmarked it offline against
# 11,578 corpus spans on o200k — the literals themselves cost 63,699 tokens and
# the ⟦L00⟧ placeholders standing in for them cost 92,624. The freeze step was
# ADDING 29,000 tokens before the rewriter saved a single one, and the penalty
# grows on newer tokenizers.
#
# `[[` and `]]` are plain ASCII, sit in every vocabulary, and cut placeholder
# cost 27%. `<L00>` measured cheaper still (−45%) and is deliberately NOT used:
# the plan rejected angle brackets because models read them as markup and
# rewrite them, and that is a behavioural risk a cost benchmark cannot see.
OPEN_DELIM  = "[["
CLOSE_DELIM = "]]"

# Bracket shapes a model might substitute for our delimiters, or that a
# normalizing surface might introduce. Used by checks 3 and 4 to tell "mangled
# our placeholder" apart from "wrote something unrelated".
_LOOKALIKE_OPEN  = "[({⟦〚【「⁅［"
_LOOKALIKE_CLOSE = "])}⟧〛】」⁆］"

# Bypass thresholds. A message that is mostly frozen has nothing left to
# compress, and rewriting it spends tokens to achieve nothing (review §3).
#
# Both numbers are measured, not guessed. Across the 2,951-record snapshot the
# frozen-character distribution runs mean 7.0%, p90 15.5%, p99 27.4%, max 43.2%
# — so a 40% gate costs about 0.1% of traffic.
#
# 🔑 The dense tail is in SHORT messages, not long ones. The plan reassured
# itself by checking the 250+ word band (14.4% frozen) — the right check on the
# wrong end. All five densest messages in the corpus are under 80 words, which
# is also the band with the lowest compression target. That is why the second
# threshold is a floor on the compressible REMAINDER rather than on message
# length. María's recall pass, 2026-08-07 §3.
DEFAULT_MAX_FROZEN_RATIO       = 0.40
DEFAULT_MIN_COMPRESSIBLE_WORDS = 40


# ──────────────────────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────────────────────

@dataclass( frozen=True )
class Span:
    """One candidate literal located in the source text."""
    start : int
    end   : int
    text  : str
    kind  : str
    tier  : str

    @property
    def length( self ):
        return self.end - self.start


@dataclass( frozen=True )
class Placeholder:
    """
    One frozen literal and the opaque token standing in for it.

    Placeholders are occurrence-unique, NOT literal-unique. The plan originally
    specified "same literal -> same placeholder"; the expert review overrode it
    (§4) because collapsing occurrences destroys provenance — two copies of the
    same sha in two different claims can both survive while swapping claims,
    and nothing downstream can tell. `group_id` keeps the equivalence
    relationship as metadata, which is where it belongs.
    """
    token            : str
    literal          : str
    kind             : str
    tier             : str
    clause_index     : int
    occurrence_index : int
    group_id         : int
    # Whether the literal was ALREADY butted against a word character when it
    # was sent out. Without this the boundary check cannot tell "the model glued
    # a plural s onto a token" apart from "this literal was embedded in a word
    # all along", and it fails on ordinary corpus text. See validate() check 3.
    left_adjacent    : bool = False
    right_adjacent   : bool = False


@dataclass( frozen=True )
class FrozenMessage:
    """The result of freezing one DM body."""
    original           : str
    frozen_text        : str
    placeholders       : tuple
    namespace          : str
    clause_spans       : tuple
    # Literals checked in place rather than substituted — see _VERIFY_PATTERNS.
    # Counted over the text with placeholders removed, so the same measurement
    # can be taken of the rewrite and compared like for like.
    verify_counts      : dict
    frozen_char_ratio  : float
    compressible_words : int
    bypass_reason      : str = None

    @property
    def should_bypass( self ):
        """True when this message must be delivered as-is, without a rewrite."""
        return self.bypass_reason is not None

    @property
    def tokens( self ):
        return tuple( p.token for p in self.placeholders )

    def by_token( self ):
        return { p.token: p for p in self.placeholders }


@dataclass
class ValidationResult:
    """
    Outcome of checking a rewritten body against what was sent to the rewriter.

    `violations` are structural and disqualifying — on any of them the caller
    delivers the original. `warnings` are telemetry: real signals that are too
    weak to gate delivery on, chiefly relocation, which the review is explicit
    cannot be caught structurally.
    """
    ok         : bool                = True
    violations : list                = field( default_factory=list )
    warnings   : list                = field( default_factory=list )
    checks     : dict                = field( default_factory=dict )

    def fail( self, check, detail ):
        self.ok = False
        self.violations.append( ( check, detail ) )
        self.checks[ check ] = False

    def warn( self, check, detail ):
        self.warnings.append( ( check, detail ) )

    def passed( self, check ):
        self.checks.setdefault( check, True )


# ──────────────────────────────────────────────────────────────────────────────
# Extraction
# ──────────────────────────────────────────────────────────────────────────────

def extract_spans( text, tier="HARD+SOFT" ):
    """
    Find every candidate literal in text.

    Requires:
        - text is a string
        - tier is "HARD" or "HARD+SOFT"

    Ensures:
        - returns a list of Span, possibly overlapping
        - every Span satisfies text[ s.start:s.end ] == s.text
        - does not mutate text

    Raises:
        - ValueError if tier is not one of the two accepted values
    """
    if tier not in ( "HARD", "HARD+SOFT" ):
        raise ValueError( f"tier must be 'HARD' or 'HARD+SOFT', got {tier!r}" )

    want_soft = ( tier == "HARD+SOFT" )
    spans     = []

    for kind, kind_tier, pattern in _PATTERNS:
        # VERIFY-tier classes are never substituted — they are checked where
        # they stand, because a placeholder costs more than the literal does.
        if kind_tier == "VERIFY": continue
        if kind_tier == "SOFT" and not want_soft: continue
        for m in pattern.finditer( text ):
            if m.start() == m.end(): continue
            spans.append( Span( m.start(), m.end(), m.group( 0 ), kind, kind_tier ) )

    return spans


def resolve_spans( spans ):
    """
    Reduce overlapping candidates to one non-overlapping set.

    The review (§2) called for exactly this instead of a sequence of
    independent regex replacements: "a quoted span containing backticks
    containing a SHA should become one non-overlapping extracted span, not
    three nested substitutions."

    Precedence, in order:
        1. longest span wins  — the enclosing construct beats what it encloses
        2. taxonomy rank      — earlier in _PATTERNS wins a length tie
        3. leftmost           — deterministic final tiebreak

    Requires:
        - spans is an iterable of Span

    Ensures:
        - returns a list of Span sorted by start, no two of which overlap
        - the result is a subset of the input
        - the result is deterministic for a given input
    """
    ordered  = sorted( spans, key=lambda s: ( -s.length, _KIND_RANK[ s.kind ], s.start ) )
    accepted = []

    for candidate in ordered:
        clash = False
        for kept in accepted:
            if candidate.start < kept.end and kept.start < candidate.end:
                clash = True
                break
        if not clash: accepted.append( candidate )

    return sorted( accepted, key=lambda s: s.start )


# ──────────────────────────────────────────────────────────────────────────────
# Clause segmentation
# ──────────────────────────────────────────────────────────────────────────────

_CLAUSE_SPLIT = re.compile( r"(?<=[.!?;:])\s+|\n+" )


def segment_clauses( text ):
    """
    Split text into clause spans.

    Clause identity is what makes relocation detectable at all: a placeholder
    that stays inside its own clause cannot have been re-attached to a
    different claim. The review calls clause confinement "the cheapest
    meaningful improvement" over bare order-monotonicity.

    Requires:
        - text is a string

    Ensures:
        - returns a tuple of (start, end) covering text with no gaps or overlaps
        - concatenating text[s:e] over the result reproduces text exactly
        - returns ((0, len(text)),) for text with no clause boundary
    """
    if not text: return ( ( 0, 0 ), )

    bounds = []
    cursor = 0

    for m in _CLAUSE_SPLIT.finditer( text ):
        bounds.append( ( cursor, m.end() ) )
        cursor = m.end()

    if cursor < len( text ): bounds.append( ( cursor, len( text ) ) )

    return tuple( bounds ) if bounds else ( ( 0, len( text ) ), )


def count_verify_literals( text, namespace ):
    """
    Count the verify-tier literals standing in text, ignoring placeholders.

    Placeholders are stripped first so that digits inside a token body cannot
    be mistaken for content. The same stripping is applied to both sides of the
    comparison, which is what makes the counts comparable.

    Removable boilerplate is stripped first and on both sides of the
    comparison, so the rewriter deleting a leading salute is not read as
    corrupting a literal.

    Requires:
        - text is a string
        - namespace is the FrozenMessage namespace ("" when none)

    Ensures:
        - returns a dict mapping literal -> occurrence count
        - placeholder tokens contribute nothing to the result
        - declared removable boilerplate contributes nothing to the result
    """
    stripped = _token_pattern( namespace ).sub( " ", text )

    for _, pattern in _REMOVABLE_BOILERPLATE:
        stripped = pattern.sub( " ", stripped )

    counts = {}

    for _, pattern in _verify_patterns():
        for m in pattern.finditer( stripped ):
            counts[ m.group( 0 ) ] = counts.get( m.group( 0 ), 0 ) + 1

    return counts


def _clause_of( position, clause_spans ):
    for i, ( start, end ) in enumerate( clause_spans ):
        if start <= position < end: return i
    return len( clause_spans ) - 1


# ──────────────────────────────────────────────────────────────────────────────
# Nonce
# ──────────────────────────────────────────────────────────────────────────────

def _derive_namespace( text ):
    """
    Derive a per-message namespace, but only when the plain form could collide.

    The review preferred a namespace over escaping ("a per-message namespace or
    nonce is preferable to merely escaping collisions") because escaping has to
    be undone, and undoing it is another place to be wrong.

    A namespace on EVERY message would be honest and expensive: it is 2-3 extra
    tokens on every placeholder, paid on all traffic to defend against
    something that occurs in almost none of it. So it is empty by default and
    appears only on messages that could actually collide.

    "Could collide" is judged by the validator's own matchers, not by the exact
    delimiter. The corpus contains `(L207)` and `(L345)` written as ordinary
    line references, which the loose matcher reads as a mangled placeholder and
    the validator then rejects as invented. Anything those matchers would trip
    on gets a namespace, which puts the prose out of their reach.

    Requires:
        - text is a string

    Ensures:
        - returns "" when nothing in text resembles a placeholder
        - otherwise returns lowercase hex + "_" such that OPEN_DELIM + result
          does not occur anywhere in text
        - deterministic: the same text always yields the same namespace
    """
    collides = (
        OPEN_DELIM in text
        or _loose_token_pattern( "" ).search( text ) is not None
        or _naked_token_pattern( "" ).search( text ) is not None
    )
    if not collides: return ""

    digest  = hashlib.sha256( text.encode( "utf-8" ) ).hexdigest()
    attempt = 0

    while True:
        width     = 4 + ( attempt // len( digest ) )
        start     = ( attempt * 4 ) % len( digest )
        candidate = ( digest + digest )[ start : start + width ] + "_"
        if ( OPEN_DELIM + candidate ) not in text: return candidate
        attempt += 1


def _token_pattern( namespace ):
    """Exact parser for this message's placeholders — never a loose replace."""
    return re.compile(
        re.escape( OPEN_DELIM ) + re.escape( namespace ) +
        r"L(\d+)" + re.escape( CLOSE_DELIM )
    )


def _loose_token_pattern( namespace ):
    """
    Deliberately sloppy matcher for things that were *meant* to be placeholders.

    This is the instrument behind check 3. Comparing its hit count against the
    exact parser's is what turns "the model mangled a token" from a list of
    shapes to enumerate into a single measurement: any split, truncation,
    dropped bracket, or substituted delimiter changes one count and not the
    other.
    """
    return re.compile(
        "[" + re.escape( _LOOKALIKE_OPEN ) + "]{1,2}"
        r"\s*" + re.escape( namespace.rstrip( "_" ) ) + r"_?\s*[Ll]\s*\d+\s*"
        "[" + re.escape( _LOOKALIKE_CLOSE ) + "]{1,2}"
    )


def _naked_token_pattern( namespace ):
    """Placeholder bodies whose delimiters were stripped entirely."""
    return re.compile(
        r"(?<![\w\[({])" + re.escape( namespace ) + r"L\d{2,}(?![\w\])}])"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Freeze
# ──────────────────────────────────────────────────────────────────────────────

def freeze( text, tier="HARD+SOFT",
            max_frozen_ratio=DEFAULT_MAX_FROZEN_RATIO,
            min_compressible_words=DEFAULT_MIN_COMPRESSIBLE_WORDS ):
    """
    Replace every resolved literal in text with an opaque placeholder.

    Requires:
        - text is a string
        - tier is "HARD" or "HARD+SOFT"
        - max_frozen_ratio is a float in (0, 1]
        - min_compressible_words is a non-negative integer

    Ensures:
        - returns a FrozenMessage whose .original is text unchanged
        - restore(result.frozen_text, result) == text, exactly, byte for byte
        - placeholders are occurrence-unique; identical literals share group_id
        - placeholder tokens do not occur in the original text
        - sets .bypass_reason when the message is not worth rewriting

    Raises:
        - ValueError if tier is invalid or max_frozen_ratio is out of range
    """
    if not ( 0 < max_frozen_ratio <= 1 ):
        raise ValueError( f"max_frozen_ratio must be in (0, 1], got {max_frozen_ratio}" )

    spans        = resolve_spans( extract_spans( text, tier=tier ) )
    clause_spans = segment_clauses( text )

    groups       = {}
    placeholders = []
    out          = []
    cursor       = 0
    namespace    = _derive_namespace( text )

    for ordinal, span in enumerate( spans ):
        clause = _clause_of( span.start, clause_spans )

        if span.text not in groups: groups[ span.text ] = len( groups )

        # The token carries an ordinal and NOTHING else.
        #
        # The review floated typed, clause-scoped tokens (⟦S02_PATH00⟧) so the
        # model could see structure. Two measurements killed that: the type
        # label is not trustworthy in the first place — the port pattern fires
        # on line numbers — and every extra character is paid on every
        # placeholder across all traffic. Kind, clause and equivalence group all
        # live in the Placeholder record instead, which is where the review
        # wanted the equivalence relationship anyway. Nothing is lost; the map
        # holds strictly more than the token ever could.
        token = f"{OPEN_DELIM}{namespace}L{ordinal:02d}{CLOSE_DELIM}"

        before = text[ span.start - 1 ] if span.start > 0        else ""
        after  = text[ span.end ]       if span.end < len( text ) else ""

        placeholders.append( Placeholder(
            token            = token,
            literal          = span.text,
            kind             = span.kind,
            tier             = span.tier,
            clause_index     = clause,
            occurrence_index = ordinal,
            group_id         = groups[ span.text ],
            left_adjacent    = bool( before ) and ( before.isalnum() or before == "_" ),
            right_adjacent   = bool( after )  and ( after.isalnum()  or after  == "_" ),
        ) )

        out.append( text[ cursor : span.start ] )
        out.append( token )
        cursor = span.end

    out.append( text[ cursor: ] )
    frozen_text = "".join( out )

    frozen_chars = sum( s.length for s in spans )
    ratio        = ( frozen_chars / len( text ) ) if text else 0.0

    # Words that survive freezing are the only material a rewriter can act on.
    residue            = _token_pattern( namespace ).sub( " ", frozen_text )
    compressible_words = len( residue.split() )

    bypass = None
    if ratio > max_frozen_ratio:
        bypass = f"frozen_ratio {ratio:.2f} exceeds {max_frozen_ratio:.2f}"
    elif compressible_words < min_compressible_words:
        bypass = f"only {compressible_words} compressible words (min {min_compressible_words})"

    return FrozenMessage(
        original           = text,
        frozen_text        = frozen_text,
        placeholders       = tuple( placeholders ),
        namespace          = namespace,
        verify_counts      = count_verify_literals( frozen_text, namespace ),
        clause_spans       = clause_spans,
        frozen_char_ratio  = ratio,
        compressible_words = compressible_words,
        bypass_reason      = bypass,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Validate
# ──────────────────────────────────────────────────────────────────────────────

def validate( rewritten, frozen_msg ):
    """
    Check a rewritten body against the placeholders that were sent out.

    The six checks are the plan's, with the review's correction to check 6: a
    rewritten message cannot be byte-equal to the original, so the byte-equality
    guarantee belongs to the extractor/restorer round trip alone, and what is
    checked here is that every mapped literal and occurrence survives.

    Requires:
        - rewritten is a string
        - frozen_msg is a FrozenMessage

    Ensures:
        - returns a ValidationResult
        - result.ok is True only if checks 1-4 all pass
        - check 5 (order) records a warning and never sets ok False
        - never raises on adversarial input; malformed text becomes a violation
    """
    result   = ValidationResult()
    pattern  = _token_pattern( frozen_msg.namespace )
    expected = frozen_msg.by_token()

    found = list( pattern.finditer( rewritten ) )
    found_tokens = [ m.group( 0 ) for m in found ]

    # ── Check 1: set equality ────────────────────────────────────────────────
    expected_set = set( expected )
    found_set    = set( found_tokens )

    missing = expected_set - found_set
    extra   = found_set - expected_set

    if missing: result.fail( "set_equality", f"omitted: {sorted( missing )}" )
    if extra:   result.fail( "set_equality", f"invented: {sorted( extra )}" )
    result.passed( "set_equality" )

    # ── Check 2: multiplicity ────────────────────────────────────────────────
    for token in expected:
        want = 1                                   # occurrence-unique by construction
        got  = found_tokens.count( token )
        if got != want:
            result.fail( "multiplicity", f"{token} appears {got}x, expected {want}x" )
    result.passed( "multiplicity" )

    # ── Check 3: boundary integrity ──────────────────────────────────────────
    #
    # Two sloppy matchers do the work here. Anything that was *meant* to be a
    # placeholder but is not exactly one shows up as a difference between the
    # loose count and the exact count. That turns "the model mangled a token"
    # from a list of shapes to enumerate — split, truncated, single-bracketed,
    # curly-quoted, spaced out — into one comparison that catches all of them.
    loose_hits = len( _loose_token_pattern( frozen_msg.namespace ).findall( rewritten ) )
    if loose_hits != len( found_tokens ):
        result.fail(
            "boundary_integrity",
            f"{loose_hits} placeholder-like spans but only {len( found_tokens )} parse exactly "
            f"— one was split, truncated, or had a delimiter altered"
        )

    naked = _naked_token_pattern( frozen_msg.namespace ).findall( rewritten )
    if naked:
        result.fail( "boundary_integrity", f"{len( naked )} placeholder body/bodies lost their delimiters" )

    # Absorption is judged against how the token was SENT, not against an
    # absolute rule. A literal can legitimately sit flush against a word
    # character in the source — that is ordinary in this corpus — and an
    # absolute check calls every one of those a violation. What is a violation
    # is adjacency the model INTRODUCED: a token that went out standing alone
    # and came back with text welded to it.
    for m in found:
        token = m.group( 0 )
        if token not in expected: continue
        sent   = expected[ token ]
        before = rewritten[ m.start() - 1 ] if m.start() > 0             else ""
        after  = rewritten[ m.end() ]       if m.end() < len( rewritten ) else ""

        if before and ( before.isalnum() or before == "_" ) and not sent.left_adjacent:
            result.fail( "boundary_integrity", f"{token} absorbed a left neighbour {before!r}" )
        if after and ( after.isalnum() or after == "_" ) and not sent.right_adjacent:
            result.fail( "boundary_integrity", f"{token} absorbed a right neighbour {after!r}" )

    result.passed( "boundary_integrity" )

    # ── Check 4: no invented placeholders ────────────────────────────────────
    #
    # Anything shaped like one of OUR placeholders that we did not send.
    #
    # ⚠️ This must be anchored on the token shape, not on "bracketed text".
    # Bracketed words are ordinary prose in this corpus — status markers like
    # [done] and [dropped] appear constantly — and a rule broad enough to catch
    # any bracketed span rejects real traffic wholesale. Caught by running the
    # identity round trip across all 2,951 corpus bodies.
    for m in _loose_token_pattern( frozen_msg.namespace ).finditer( rewritten ):
        if m.group( 0 ) not in expected_set:
            result.fail( "no_invented", f"placeholder-shaped text not sent: {m.group( 0 )!r}" )
    result.passed( "no_invented" )

    # ── Check 7: verify-tier literals, checked in place ──────────────────────
    #
    # The second tier. These were never substituted, so there is no placeholder
    # to inspect — the assertion is that the multiset of them is unchanged.
    # Cheap, exact for omission and mutation, and blind to relocation by
    # construction: swap two numbers and the multiset is identical. Check 5's
    # clause confinement is the companion signal, and it is a warning, so this
    # pair detects the ordering failure without being able to gate on it.
    got_counts = count_verify_literals( rewritten, frozen_msg.namespace )

    for literal, want in frozen_msg.verify_counts.items():
        have = got_counts.get( literal, 0 )
        if have != want:
            result.fail( "verify_literals", f"{literal!r} appears {have}x, expected {want}x" )

    for literal, have in got_counts.items():
        if literal not in frozen_msg.verify_counts:
            result.fail( "verify_literals", f"{literal!r} appeared {have}x but was never sent" )

    result.passed( "verify_literals" )

    # ── Check 5: order and clause confinement — WARNING ONLY ─────────────────
    #
    # 🔴 READ THIS BEFORE TRUSTING A CLEAN RESULT.
    #
    # Relocation is the honest limit of this method, and these two signals are
    # WEAKER than they look. A rewrite can swap which claim each placeholder
    # belongs to while leaving the tokens in ascending order inside a single
    # clause — "The bug is in [[L00]] and the fix is in [[L01]]" coming back as
    # "Fix in [[L00]] and bug in [[L01]]" — and neither signal fires. It is not
    # a tuning problem; the information is not present in the structure.
    #
    # Do not read "no warnings" as "no relocation". Catching it needs a
    # semantic check or a human, and neither exists yet.
    sequence = [ expected[ t ].occurrence_index for t in found_tokens if t in expected ]
    if sequence != sorted( sequence ):
        result.warn( "order", "placeholder order changed — possible relocation" )

    rewritten_clauses = segment_clauses( rewritten )

    # When the rewrite changed the clause structure, origin and landing indices
    # are not comparable and confinement cannot be evaluated.
    #
    # It used to be skipped silently in that case, which inverted the signal:
    # compression that actually worked reshapes clauses, so the check went quiet
    # exactly when it was most needed and spoke up only on rewrites that had
    # barely changed anything. Say so instead of saying nothing.
    if len( rewritten_clauses ) != len( frozen_msg.clause_spans ):
        result.warn(
            "clause_confinement_unavailable",
            f"clause count changed {len( frozen_msg.clause_spans )} -> {len( rewritten_clauses )}; "
            f"relocation could not be checked for this message"
        )
    else:
        for m in found:
            token = m.group( 0 )
            if token not in expected: continue
            landed = _clause_of( m.start(), rewritten_clauses )
            origin = expected[ token ].clause_index
            if landed != origin:
                result.warn( "clause_confinement", f"{token} moved clause {origin} -> {landed}" )

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Restore
# ──────────────────────────────────────────────────────────────────────────────

def restore( rewritten, frozen_msg, strict=True ):
    """
    Put the literals back.

    Fail-closed is the entire safety posture. If restoration cannot be
    completed exactly, the caller delivers the original uncompressed: the worst
    case becomes "no compression on this message" instead of "a corrupted line
    number someone acts on."

    Requires:
        - rewritten is a string
        - frozen_msg is a FrozenMessage
        - strict is a bool

    Ensures:
        - returns rewritten with every placeholder replaced by its exact literal
        - restore(fm.frozen_text, fm) == fm.original, byte for byte
        - uses an exact token parser, never a general string replace
        - when strict, refuses to return a partially-restored string

    Raises:
        - ValueError when strict and validation found any structural violation
    """
    if strict:
        verdict = validate( rewritten, frozen_msg )
        if not verdict.ok:
            raise ValueError(
                "refusing to restore — structural violations: " +
                "; ".join( f"{c}: {d}" for c, d in verdict.violations )
            )

    lookup = frozen_msg.by_token()

    def _swap( m ):
        token = m.group( 0 )
        if token not in lookup:
            raise ValueError( f"unknown placeholder in namespace: {token!r}" )
        return lookup[ token ].literal

    return _token_pattern( frozen_msg.namespace ).sub( _swap, rewritten )


def compress_or_original( rewritten, frozen_msg ):
    """
    The delivery decision, in one call.

    Requires:
        - rewritten is a string (the model's output, still holding placeholders)
        - frozen_msg is a FrozenMessage

    Ensures:
        - returns (text_to_deliver, fallback_reason)
        - fallback_reason is None when the compressed form is safe to deliver
        - never returns text containing an unrestored placeholder
        - never raises
    """
    if frozen_msg.should_bypass:
        return frozen_msg.original, f"bypass: {frozen_msg.bypass_reason}"

    verdict = validate( rewritten, frozen_msg )
    if not verdict.ok:
        return frozen_msg.original, "; ".join( f"{c}: {d}" for c, d in verdict.violations )

    try:
        return restore( rewritten, frozen_msg, strict=False ), None
    except ValueError as e:
        return frozen_msg.original, f"restore failed: {e}"


# ──────────────────────────────────────────────────────────────────────────────

def quick_smoke_test():
    """Exercise the round trip on the plan's own worked example."""
    import cosa.utils.util as du

    du.print_banner( "dm_compression.freeze smoke test" )

    original = "The leak is at judge.py:572, shipped in d256e25a."
    fm       = freeze( original )

    print( f"original : {original}" )
    print( f"frozen   : {fm.frozen_text}" )
    print( f"literals : {[ p.literal for p in fm.placeholders ]}" )

    identity = restore( fm.frozen_text, fm )
    print( f"identity round trip : {'PASS' if identity == original else 'FAIL'}" )

    # A rewrite that shortens the prose but leaves the tokens alone.
    rewritten = fm.frozen_text.replace( "The leak is at", "Leak at" ).replace( "shipped in", "fixed in" )
    verdict   = validate( rewritten, fm )
    print( f"validate rewritten  : {'PASS' if verdict.ok else 'FAIL ' + str( verdict.violations )}" )
    print( f"restored            : {restore( rewritten, fm )}" )

    # Fail-closed: drop a token and confirm we refuse.
    mangled = rewritten.replace( fm.placeholders[ 0 ].token, "" )
    refused = not validate( mangled, fm ).ok
    print( f"fail-closed on omit : {'PASS' if refused else 'FAIL'}" )


if __name__ == "__main__":
    quick_smoke_test()
