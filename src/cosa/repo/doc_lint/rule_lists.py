# Frozen at 521f36f09, ruling b42eb0de (Rick, 2026-09-30): any change to the list contents needs his word.
"""
Frozen lists for the docstring and markdown linters (documentation-standard plan).

Holds the acronym allowlist, the tic list, the bare-reference predicate, the dated-banner
and agent-imperative patterns, and the provisional thresholds. Stdlib only, so the same file
can be vendored into lupin-mobile's tool/ directory.

These lists are frozen by sha before any labelling sample is drawn. Changing one
after the freeze invalidates the precision and recall measured against it.
"""

import re

# Rule 4: an ALL-CAPS word is emphasis when its lowercase form is an English word (measured
# against the vendored word list, see word_list.py). Acronyms such as JSON or LLM are not words,
# so they need no list. This set holds only the dictionary words that are also conventional
# acronyms, HTTP verbs or git refs, which the word-list test would wrongly flag. A token with an
# underscore (LUPIN_ROOT), a digit, a hyphen neighbour (D6-STRICT) or a quote or backtick around
# it is exempt by predicate.
CAPS_WORD_EXCEPTIONS = frozenset( [
    "ID", "IDS", "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "NULL", "MM", "DD", "RAM",
    "REST", "KISS", "TODO", "FIFO", "ANN", "OOM", "ORM", "SHA", "CWD", "DOM", "PEFT", "LORA", "CC", "CRUD",
] )
# Spans where a capitalised word is quoted, not emphasised: "ALLOW", 'KISS', `CODE`.
QUOTED_SPAN_REGEX = re.compile( r"\"[^\"\n]*\"|(?<![\w])'[^'\n]*'(?![\w])|`[^`\n]*`" )

# Rule 5: phrases that add tone and no constraint. Matched case-insensitively on word
# boundaries. "rather than", "silently", "verbatim" and "the defect" were measured and left
# off: they carry technical meaning in this corpus.
TIC_PHRASES = (
    r"deliberately",
    r"by construction",
    r"load[- ]bearing",
    r"the (?:whole )?point is",
    r"(?:that|which) is the point",
    r"the whole point",
    r"exactly the",
    r"by design",
    r"on purpose",
    r"honestly",
    r"genuinely",
    r"suspenders",
    r"(?:reads|looks) exactly like",
    r"full stop",
    r"no exceptions",
    r"the lesson",
    r"the trap",
    r"the hazard",
    r"is the red",
)
TIC_REGEX = re.compile( r"\b(?:" + "|".join( TIC_PHRASES ) + r")\b", re.IGNORECASE )

# Rule 4: emphasis glyphs. The warning sign is matched with or without its variation selector.
EMPHASIS_GLYPHS = ( "⚠", "\U0001f534", "⇒" )

# Rule 6: a reference with no path. Section marks are handled separately, because a section
# mark that follows a path in the same paragraph is resolved (see is_section_ref_resolved).
# ID_REF_REGEX is the spec's own definition and feeds the baseline column; the wider
# ID_REF_EXTENDED_REGEX and BARE_SHA_REGEX feed the rule.
ID_REF_REGEX          = re.compile( r"\b(?:row|bug|task|ts)[\s\-:`'\"#]*(?=[0-9a-f]*\d)[0-9a-f]{8}\b", re.IGNORECASE )
ID_REF_EXTENDED_REGEX = re.compile( r"\b(?:rows?|bugs?|tasks?|ts|decision|job|pr|ticket)[\s\-:`'\"#]*(?=[0-9a-f]*\d)[0-9a-f]{8}\b", re.IGNORECASE )
# A standalone 8-hex token with a digit and a letter, not part of a path, filename or longer word.
# Whether a git sha counts as a reference that must resolve is Rick's call (Tiberius, L2).
BARE_SHA_REGEX        = re.compile( r"(?<![\w\-/=.])(?=[0-9a-f]*\d)(?=\d*[a-f])[0-9a-f]{8}(?![\w\-/=.])" )
RULING_REF_REGEX      = re.compile( r"(?i:\bruling)\s+(?:#?\d+(?!\d|[-./]\d)|[A-Z]\d?=?[A-Z]?\b)" )
AC_REF_REGEX          = re.compile( r"\bAC[-\s]?\d+(?:[.\-]\d+)*\b" )
STEP_REF_REGEX        = re.compile( r"(?i:\b(?:step|phase|stage|item|option)s?)\s+(?:\d+(?:\.\d+)*[a-z]?\b|[A-Z]\b|\([a-z]\))" )
# Decision or case labels such as D4, R1, S6, L2. Version labels, the P0 to P5 priorities,
# HTML headings, S3 and hex colours are exempt.
LABEL_REF_REGEX       = re.compile( r"(?<![#\w])(?![PV]\d\b|H[1-6]\b|S3\b)[A-Z]\d{1,2}\b" )
SECTION_REGEX         = re.compile( "\u00a7\\s*[\\w.#]+" )
PATH_REGEX            = re.compile( r"(?:[\w.\-]+/)+[\w.\-]+\.\w{1,5}|\b[\w\-]+\.(?:md|py|dart|ts|js|ini|ya?ml|json|sh|sql|tsv)\b" )
# How far around a section mark a path counts as its target, within the same paragraph.
SECTION_PATH_LOOKBACK  = 120
SECTION_PATH_LOOKAHEAD = 60

# Rule 7: dated banners and corrections belong in history. An ISO date in prose is the
# predicate; the verb pattern and the banner-line pattern are kept as subsets that name the cause.
ISO_DATE_REGEX     = re.compile( r"\b20\d\d-\d\d-\d\d\b" )
DATED_BANNER_REGEX = re.compile(
    r"\b(?:added|updated|fixed|measured|ruled|corrected|changed|landed|retired|re-measured)"
    r"\s+(?:on\s+)?20\d\d[-./]\d\d[-./]\d\d"
    r"|\b(?:FORENSIC UPDATE|UPDATE|CORRECTION|RETRACTED)\b[^\n]{0,60}20\d\d[-./]\d\d[-./]\d\d"
    r"|^\s*(?:\u26a0\ufe0f?\s*)?(?:FORENSIC UPDATE|UPDATE|CORRECTION|RETRACTED)\b",
    re.IGNORECASE | re.MULTILINE
)

# Plan 1 section 4.1: text addressed to a model or agent. Docstrings are read as prompts.
AGENT_IMPERATIVE_REGEX = re.compile(
    r"\bignore (?:all |any )?(?:previous|prior|above) instructions\b"
    r"|\byou (?:must|should|need to|are to|will)\b"
    r"|\bdisregard\b"
    r"|\bas an? (?:ai|llm|assistant)\b"
    r"|\bnote to (?:the )?(?:model|agent|assistant|claude)\b",
    re.IGNORECASE
)

# Provisional thresholds. Rick sets the real ones from pilot data at the Phase 3 sign-off.
SUMMARY_MAX_CHARS   = 90
SENTENCE_MAX_WORDS  = 25
PREFACE_MAX_LINES   = 6
DOCSTRING_MAX_LINES = 40
DART_BLOCK_MAX_LINES = 20
