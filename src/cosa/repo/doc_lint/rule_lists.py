"""
Frozen lists for the docstring and markdown linters (plan 1, Phase 0 step 4).

Holds the acronym allowlist, the tic list, the bare-reference predicate, the dated-banner
and agent-imperative patterns, and the provisional thresholds. Stdlib only, so the same file
can be vendored into lupin-mobile's tool/ directory.

These lists are frozen by sha before any labelling sample is drawn (ruling B8). Changing one
after the freeze invalidates the precision and recall measured against it.
"""

import re

# Rule 4: ALL-CAPS words are banned outside this set. A token that contains an underscore
# (LUPIN_ROOT, JOB_ARG_CONTRACTS) is an identifier, not emphasis, and is exempt by predicate.
ACRONYM_ALLOWLIST = frozenset( [
    # data formats and protocols
    "JSON", "JSONL", "JSONB", "XML", "YAML", "CSV", "HTML", "CSS", "SVG", "PNG", "MP3", "MP4",
    "WAV", "ASCII", "UTF", "CDATA", "SQL", "DDL", "ORM", "CRUD", "REST", "API", "HTTP", "HTTPS",
    "URL", "URI", "JWT", "SSE", "WS", "SMTP", "TLS", "SSH", "IP", "IANA", "POSIX", "FIFO",
    "UUID", "SHA", "ISO", "EOF", "ID", "IDS", "INI", "IO", "OS",
    # http verbs and git refs
    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "WIP", "PR", "NULL",
    # systems and hardware
    "DB", "PG", "KV", "GPU", "CPU", "VRAM", "RAM", "CUDA", "OOM", "PID", "PPID", "CWD",
    "SIGTERM", "SIGKILL", "DOM", "GCS", "GCP", "HNSW", "FK", "TTL", "HWM", "PCM", "ADC",
    "TPM", "KB", "MB", "GB", "USD", "UTC", "EDT", "EST",
    # date and time placeholders
    "YYYY", "MM", "DD", "HH",
    # project and domain names
    "LLM", "AI", "MCP", "CLI", "SDK", "UI", "UX", "TTS", "DM", "CC", "CJ", "COSA", "LUPIN",
    "TFE", "BFE", "SWE", "PEFT", "LORA", "ANN", "FCM", "JS", "README", "TODO", "E2E",
    "PYTHONPATH", "DATA01", "S3",
    # priority labels
    "P0", "P1", "P2", "P3", "P4", "P5",
] )

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
# mark that follows a path on the same line is resolved (see is_section_ref_resolved).
ID_REF_REGEX     = re.compile( r"\b(?:row|bug|task|ts)[\s\-:`'\"#]*(?=[0-9a-f]*\d)[0-9a-f]{8}\b", re.IGNORECASE )
RULING_REF_REGEX = re.compile( r"\bruling\s+(?:#?\d+|[A-Z]\d?=?[A-Z]?\b)", re.IGNORECASE )
AC_REF_REGEX     = re.compile( r"\bAC[-\s]?\d+(?:[.\-]\d+)*\b" )
STEP_REF_REGEX   = re.compile( r"\bstep\s+\d+[a-z]\b", re.IGNORECASE )
# Decision or case labels such as D4, R1, S6, L2. Version labels (V1) and the P0 to P5
# priorities are exempt.
LABEL_REF_REGEX  = re.compile( r"\b(?![PV]\d\b)[A-Z]\d{1,2}\b" )
SECTION_REGEX    = re.compile( "§\\s*[\\w.#]+" )
PATH_REGEX       = re.compile( r"(?:[\w.\-]+/)+[\w.\-]+\.\w{1,5}|\b[\w\-]+\.(?:md|py|dart|ts|js|ini|ya?ml|json|sh|sql|tsv)\b" )
# How far around a section mark a path counts as its target.
SECTION_PATH_LOOKBACK  = 120
SECTION_PATH_LOOKAHEAD = 60

# Rule 7: dated banners and corrections that belong in history.
DATED_BANNER_REGEX = re.compile(
    r"\b(?:added|updated|fixed|measured|ruled|corrected|changed|landed|retired|re-measured)"
    r"\s+(?:on\s+)?20\d\d[-./]\d\d[-./]\d\d"
    r"|\b(?:FORENSIC UPDATE|UPDATE|CORRECTION|RETRACTED)\b[^\n]{0,60}20\d\d[-./]\d\d[-./]\d\d"
    r"|^\s*(?:⚠️?\s*)?(?:FORENSIC UPDATE|UPDATE|CORRECTION|RETRACTED)\b",
    re.IGNORECASE | re.MULTILINE
)

# Plan 1 section 4.1: text addressed to a model or agent. Docstrings are read as prompts.
AGENT_IMPERATIVE_REGEX = re.compile(
    r"\bignore (?:all |any )?(?:previous|prior|above) instructions\b"
    r"|\byou (?:must|should|need to|are to|will)\b"
    r"|\b(?:always|never) (?:call|use|run|invoke|send)\b"
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
