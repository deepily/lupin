"""
Scope registry for the multi-repo doc viewer.

Built at FastAPI startup from `[Lupin: Baseline]` INI keys:

    external repos                              = name1, name2, ...
    external repo <name> path                   = /absolute/in-container/path
    external repo <name> allowed prefixes       = src/, docs/, ...

Each registered scope becomes addressable via `/api/docs/file?scope=<name>&path=<rel>`.

Built-in scopes (`docs`, `io`) are NOT in this registry — they predate it and live
inline in `docs_files.py` / `io_files.py`. The registry exposes only USER-CONFIGURED
external scopes.

Secrets blocklist (§3e) applies to ALL scopes, registered or built-in, and runs
AFTER the per-scope whitelist (defense-in-depth).

Design doc: src/rnd/v0.1.7/2026.05.12-multi-repo-doc-viewer.md
Generated on: 2026-05-12
"""

import os
import re
import json
import unicodedata
from dataclasses import dataclass, field
from typing import Optional, Tuple

import cosa.utils.util as du
from cosa.config.docview_manifest import DocviewManifest, load_manifest_for_scope


# ---------------------------------------------------------------------------
# ScopeConfig
# ---------------------------------------------------------------------------

@dataclass( frozen=True )
class ScopeConfig:
    """
    Frozen description of one external scope.

    Fields:
        name             : Short scope name (used in `?scope=<name>`).
        root             : Absolute filesystem path inside the container.
        allowed_prefixes : Tuple of path prefixes (relative to root). Empty tuple
                           AND no manifest → wildcard ("all paths under root are
                           reachable" subject to MEDIA_TYPES + secrets blocklist).
                           When a manifest is present, the manifest's
                           `allowed_prefixes` is authoritative; this field is
                           treated as the fallback for repos that ship neither.
        manifest         : Optional `DocviewManifest` loaded from
                           `<root>/.docview.yml` at build time. When present,
                           the manifest's allowed_prefixes, allowed_root_files,
                           and extra_blocklist are the authority for this scope.
        extra_blocklist_patterns: Pre-compiled regex patterns derived from
                           manifest.extra_blocklist (if any). Empty tuple
                           when no manifest or no extras.
    """

    name                     : str
    root                     : str
    allowed_prefixes         : tuple
    manifest                 : Optional[ DocviewManifest ] = None
    extra_blocklist_patterns : tuple                       = ()


# ---------------------------------------------------------------------------
# Secrets blocklist — applies to ALL scopes (built-in + external)
# ---------------------------------------------------------------------------

SECRETS_BLOCKLIST_PATTERNS = (
    # ----- Credentials (pre-existing + extensions) -----
    # Dotfiles known to carry secrets
    re.compile( r"^\.env(\.|$)" ),
    re.compile( r"^\.netrc$" ),
    re.compile( r"^\.pgpass$" ),
    re.compile( r"^\.credentials" ),                              # F4/F5: any .credentials*

    # Common credential-bearing names. The boundary is anchored to avoid
    # false-positives on substrings like "secretive_methods" or "credentialism"
    # — both legitimate filenames that should NOT be blocked.
    #
    # ⚠️ `\b` IS THE WRONG BOUNDARY HERE, and it left a real hole open.
    # An underscore is a WORD character, so `\bcredentials\b` does not match
    # inside `application_default_credentials.json` — the default filename
    # gcloud writes for Application Default Credentials. Measured 2026-08-17:
    # `credentials.json` was blocked while `application_default_credentials.json`
    # was SERVED, and the doc viewer serves anything under `src`. Found by
    # Tiffany 💍 while reviewing whether to mount those very credentials into a
    # test container — the file we were about to place on disk was the file the
    # blocklist did not cover.
    #
    # `(?<![a-z0-9])` / `(?![a-z0-9])` treat `_`, `-` and `.` as separators the
    # way a filename does, while still refusing to fire inside a longer word.
    # So `credentialism.txt` and `secretive_methods.py` stay served, and
    # `application_default_credentials.json` / `my_secrets.yaml` do not.
    re.compile( r"(?<![a-z0-9])credentials?(?![a-z0-9])", re.IGNORECASE ),
    re.compile( r"(?<![a-z0-9])secrets?(?![a-z0-9])",     re.IGNORECASE ),
    re.compile( r"(?<![a-z0-9])password(?![a-z0-9])",     re.IGNORECASE ),

    # 🔴 THREE MORE FILENAMES A REAL GOOGLE KEY CARRIES, none of which contains the
    # word "credentials" or "secret", and none covered by the service-account family
    # above. MEASURED on this branch before these lines: `adc.json`,
    # `authorized_user.json` and `firebase-adminsdk-*.json` were all SERVED, and so
    # were the `gcp-key.json` / `bigquery-key.json` shapes (`\.key$` below does not
    # fire on a `.json` file).
    #
    # `token.json` is DELIBERATELY ABSENT: it is genuinely ambiguous, the content
    # check is what catches a real one, and there is already a test asserting it stays
    # served by name. Not every credential filename belongs on a path blocklist.
    #
    # ANCHORED TO `.json` DELIBERATELY. Every candidate was measured against the whole
    # served tree first: a bare `*-key*.json` blocks `config-key-migration-map.json`
    # (30 copies of a legitimate config doc), so the key rule names providers instead.
    # These four measure ZERO hits across 907,074 files in the mounted tree.
    #
    # This is the path floor; the content check below is the payload floor. A key
    # renamed to `notes.json` defeats every pattern here and is caught there — which
    # is why both exist rather than either alone.
    re.compile( r"(?<![a-z0-9])adminsdk[^/]*\.json$",           re.IGNORECASE ),
    re.compile( r"(?<![a-z0-9])authorized[-_]user[^/]*\.json$",  re.IGNORECASE ),
    re.compile( r"^adc\.json$",                                  re.IGNORECASE ),

    # `gcp-key.json` / `bigquery-key.json` shapes. `\.key$` below does not fire on a
    # `.json` file, so these were served too. Named providers ONLY, not a bare
    # `*-key*.json`: the bare form was measured and blocks
    # `config-key-migration-map.json`, 30 copies of a legitimate config doc across
    # the tree. Provider-prefixed form measures ZERO hits on the served tree.
    re.compile( r"(?<![a-z0-9])(gcp|gcloud|gce|bigquery|firebase|aws|azure)[-_][^/]*keys?[^/]*\.json$", re.IGNORECASE ),

    # Key/cert file extensions
    re.compile( r"\.pem$", re.IGNORECASE ),
    re.compile( r"\.key$", re.IGNORECASE ),
    re.compile( r"\.pfx$", re.IGNORECASE ),
    re.compile( r"\.p12$", re.IGNORECASE ),
    re.compile( r"\.gpg$", re.IGNORECASE ),                       # F4 add
    re.compile( r"\.asc$", re.IGNORECASE ),                       # F4 add

    # ----- Service-account / key-file NAME family (bug afdc938f) -----
    # Generalised, NOT the seven literal filenames Tiffany measured as served —
    # patching this family by literal name has already failed twice. These cover the
    # separator variants of one idea ("a service-account key file"), and the CONTENT
    # check (`is_credential_file`) is what catches the name nobody predicted.
    #
    # Deliberately ABSENT: bare `token` and bare `keyfile`. Both are ambiguous by
    # name — `token.json` is a legitimate tokenizer file in ML repos — so blocking
    # them here would refuse real documents. Content decides those, correctly in
    # both directions: a tokenizer carries no private_key, a credential does.
    re.compile( r"service[-_. ]?account", re.IGNORECASE ),
    re.compile( r"\bsa[-_]key\b",         re.IGNORECASE ),
    re.compile( r"\bsvc[-_. ]?acct\b",    re.IGNORECASE ),
    re.compile( r"\bgcp[-_. ]?sa\b",      re.IGNORECASE ),

    # SSH key filenames
    re.compile( r"id_rsa",     re.IGNORECASE ),
    re.compile( r"id_ed25519", re.IGNORECASE ),
    re.compile( r"id_dsa",     re.IGNORECASE ),
    re.compile( r"id_ecdsa",   re.IGNORECASE ),

    # ----- Local config (F4: never expose per-user / per-host overrides) -----
    re.compile( r"^CLAUDE\.local\.md$" ),
    re.compile( r"\.local\.md$",   re.IGNORECASE ),
    re.compile( r"\.local\.json$", re.IGNORECASE ),
    re.compile( r"\.local\.ya?ml$", re.IGNORECASE ),
    re.compile( r"^\.gitconfig-local$" ),

    # ----- Dev artifacts (F4 + F5 case-insensitive) -----
    re.compile( r"^\.venv$",         re.IGNORECASE ),
    re.compile( r"^node_modules$",   re.IGNORECASE ),
    re.compile( r"^__pycache__$",    re.IGNORECASE ),
    re.compile( r"\.pyc$",           re.IGNORECASE ),
    re.compile( r"\.pyo$",           re.IGNORECASE ),
    re.compile( r"^dist$",           re.IGNORECASE ),
    re.compile( r"^build$",          re.IGNORECASE ),
    re.compile( r"^target$",         re.IGNORECASE ),
    re.compile( r"^\.coverage$",     re.IGNORECASE ),
    re.compile( r"^coverage$",       re.IGNORECASE ),
    re.compile( r"^\.pytest_cache$", re.IGNORECASE ),
    re.compile( r"^\.tox$",          re.IGNORECASE ),

    # ----- IDE / editor (F4 + F5 case-insensitive) -----
    re.compile( r"^\.idea$",     re.IGNORECASE ),
    re.compile( r"^\.vscode$",   re.IGNORECASE ),
    re.compile( r"^\.DS_Store$", re.IGNORECASE ),
    re.compile( r"\.swp$",       re.IGNORECASE ),
    re.compile( r"\.swo$",       re.IGNORECASE ),
    re.compile( r"^Thumbs\.db$", re.IGNORECASE ),

    # ----- Personal config / cloud (F4 + F5 case-insensitive) -----
    re.compile( r"^\.bash_history$", re.IGNORECASE ),
    re.compile( r"^\.ssh$",          re.IGNORECASE ),
    re.compile( r"^\.aws$",          re.IGNORECASE ),
    re.compile( r"^\.gnupg$",        re.IGNORECASE ),
    re.compile( r"^\.kube$",         re.IGNORECASE ),
    re.compile( r"^\.docker$",       re.IGNORECASE ),
)


# ---------------------------------------------------------------------------
# CONTENT-based credential detection (bug afdc938f)
# ---------------------------------------------------------------------------
#
# ⚠️ WHY CONTENT AND NOT SEVEN MORE FILENAMES. This family has now been patched
# twice by name. 023e72cb fixed `\bcredentials\b` failing on
# `application_default_credentials.json` — correct, and scoped to the one filename
# that had been caught rather than to the family. Tiffany then measured seven more
# still SERVED: service-account.json, sa_key.json, service_account.json,
# svc-acct.json, gcp-sa.json, token.json, keyfile.json. Adding those seven is the
# same fix that just failed, applied a third time; the eighth name nobody predicted
# is served the moment someone commits it.
#
# A name is a guess about content. The content is the fact. A GCP service-account
# key is the same secret in the same JSON shape under ANY name, so this reads the
# bytes and decides.
#
# It also cannot false-positive the way a name rule does: `token.json` and
# `keyfile.json` are ambiguous by name — a tokenizer file is legitimately called
# `token.json` in ML repos — but a tokenizer carries no `private_key`, so a content
# check blocks the credential and serves the tokenizer. That is precisely the case
# a name-only blocklist has to get wrong in one direction or the other.

# How much of a file is read to decide. Big enough to carry the signature fields of
# a service-account key or an ADC file (both are a few KB, and the fields sit near
# the top), small enough that deciding never means slurping an arbitrary file.
CREDENTIAL_SNIFF_BYTES = 8192

# The SECOND-stage bound, used only when the first window was filled by something
# that is trying to be a JSON container. Clayton measured a real ADC whose signature
# fields sat past 8192 behind one big leading field: the truncated branch scans the
# window as text, so a signature outside the window is a signature that does not
# exist. Reading further is what closes that, and it stays BOUNDED — a credential is
# a few KB, so a megabyte is generous by three orders of magnitude while still never
# meaning "slurp an arbitrary file".
CREDENTIAL_MAX_SNIFF_BYTES = 1_048_576

# The field SIGNATURES, per Tiffany's constraint 1 — a GCP service-account key is
# identified by carrying type=service_account + private_key + client_email, and a
# user ADC file by refresh_token + client_secret. Any ONE of these fields is enough
# to refuse: a document with a legitimate reason to contain `private_key` as a
# JSON key holding a real secret string is not a document, it is a key.
_CREDENTIAL_JSON_KEYS = (
    "private_key",              # GCP SA keys, and any PKCS#8 blob carried in JSON
    "private_key_id",
    "refresh_token",            # OAuth user creds — what token.json usually holds
    "client_secret",
)

_CREDENTIAL_TYPE_VALUES = (
    "service_account",
    "authorized_user",
    "external_account",
)

# PEM private-key blocks, whatever the file is called or wrapped in.
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
)

# Syntactic placeholder values — `<your client secret>`, `${CLIENT_SECRET}`,
# `{{ client_secret }}`. A credential FIELD whose value is one of these carries no
# secret, so a spec or a template that shows the field keeps being served. This is a
# shape test, not a vocabulary list: no word has to be guessed in advance, and a real
# secret cannot be spelled this way without ceasing to be the secret.
_PLACEHOLDER_VALUE = re.compile( r"^\s*(?:<[^>]*>|\$\{[^}]*\}|\{\{[^}]*\}\})\s*$" )

# A JSON \uXXXX escape. The truncated branch scans RAW TEXT, so a key spelled
# `"refresh_token"` reads as a different string there than it does once parsed.
# Putting the escapes back before the scan is what closes that.
_JSON_UNICODE_ESCAPE = re.compile( r"\\u([0-9a-fA-F]{4})" )

# What a JSON container starts with, once the invisible lead-in is gone. An ARRAY
# counts: `[ {ADC} ]` is a credential file, and reading only objects served it.
_JSON_CONTAINER_OPENERS = ( "{", "[" )

# How many JSON-shaped STRINGS one file may be re-parsed for. The walk crosses objects
# and arrays, and it used to stop at a string — so a whole key carried as JSON TEXT
# inside another JSON file was never opened. That is the normal shape of terraform
# tfvars, a kubernetes secret and a compose env file, not an exotic attack.
#
# BOUNDED on purpose: without a budget, a document full of JSON-shaped strings turns
# one serve/refuse decision into thousands of parses. Sixty-four is far past any real
# nesting — the measured shapes carry one or two — and far short of a cost anyone
# notices on a single file fetch.
CREDENTIAL_MAX_NESTED_PARSES = 64


def is_credential_file( full_path: str ) -> bool:
    """
    Return True iff the FILE AT `full_path` is credential material — FAIL CLOSED.

    The doc viewer's last line of defence: the whitelist said yes and the name
    blocklist said yes, and the bytes still get the final word.

    🔴 FAIL CLOSED (Tiffany's constraint 2). Unreadable, wrongly-encoded, gone,
    permission-denied — every one of them returns True and BLOCKS. A content check
    that serves a file it could not read is worse than no check at all, because it
    looks like protection while providing none. The one thing that must never happen
    is "I could not tell, so I served it".

    🔴 NOT GATED ON THE EXTENSION (constraint 3). Every text file is sniffed, not
    just `*.json`. Gating on `.json` would let `key.txt` walk straight through and
    would re-introduce, one layer down, the exact filename dependency this check
    exists to remove.

    🔴 BOUNDED READ, IN TWO STAGES (constraint 4). The first CREDENTIAL_SNIFF_BYTES
    decide almost every file. If that window is FILLED by something that is trying to
    be a JSON container, the read widens once to CREDENTIAL_MAX_SNIFF_BYTES, because
    a signature outside the window is a signature this function cannot see — Clayton
    measured a real credential hidden that way behind one big leading field. Both
    stages are bounded, so deciding still never means slurping an arbitrary file.

    ⚠️ ACCEPTED LIMIT, stated rather than assumed: a JSON container larger than
    CREDENTIAL_MAX_SNIFF_BYTES whose only credential material sits past that mark is
    SERVED. Closing that would mean refusing every large JSON document on the grounds
    that it might be hiding something, which costs more than it buys.

    Requires:
        - full_path is a filesystem path the caller intends to serve

    Ensures:
        - True for a JSON object AT ANY NESTING DEPTH, inside objects or arrays, or
          carried as JSON TEXT inside a string, declaring type service_account /
          authorized_user / external_account, or carrying private_key /
          private_key_id / refresh_token / client_secret with a real string value, or
          with a list holding one
        - True for any PEM PRIVATE KEY block, bare or wrapped
        - True when the file cannot be read or decoded, for ANY reason
        - False only when the prefix was read successfully AND carries no signature —
          so a tokenizer legitimately named token.json is served, while a credential
          under the same name is refused

    Raises:
        - nothing; every failure path blocks instead
    """
    try:
        with open( full_path, "r", encoding="utf-8" ) as handle:
            prefix = handle.read( CREDENTIAL_SNIFF_BYTES )
            if _the_window_may_be_hiding_the_signature( prefix ):
                prefix += handle.read( CREDENTIAL_MAX_SNIFF_BYTES - CREDENTIAL_SNIFF_BYTES )
    except Exception:
        # Unreadable, missing, permission-denied, or not utf-8 — all BLOCK.
        return True

    return _prefix_looks_like_credential( prefix )


def _the_window_may_be_hiding_the_signature( prefix: str ) -> bool:
    """
    Return True iff the first window ran out mid-file on a JSON container, which is
    the only case where reading further can change the answer.

    A file SHORTER than the window was read whole, so there is nothing further to
    see. Text that is not a JSON container is decided as prose and reading more of it
    changes nothing. Everything else stops at one window.

    Requires:
        - prefix is the text read by the first stage

    Ensures:
        - True only when the window was filled AND the text opens a JSON object or
          array once the invisible lead-in is stripped

    Raises:
        - nothing
    """
    if len( prefix ) < CREDENTIAL_SNIFF_BYTES:
        return False

    return _strip_leadin_noise( prefix )[ : 1 ] in _JSON_CONTAINER_OPENERS


def _strip_leadin_noise( text: str ) -> str:
    """
    Drop every leading character a reader cannot see, in ANY order, until a visible
    one appears.

    Requires:
        - text is decoded text (possibly empty)

    Ensures:
        - returns text with leading whitespace AND leading Unicode category Cf
          (format) characters removed, interleaved in any order
        - returns text unchanged when its first character is visible
        - returns "" for text that is entirely invisible

    Raises:
        - nothing

    WHY A CHARACTER CLASS AND NOT A LONGER lstrip() ARGUMENT: two strips in a fixed
    order cannot handle interleaving. `lstrip( "﻿" )` then `lstrip()` leaves
    `" ﻿{...}"` with the mark back at the front, which SERVED a complete ADC
    credential. Category Cf is what U+FEFF, U+200B, U+2060 and the direction marks
    are, so this closes the class rather than the one codepoint that got caught.
    """
    i = 0
    while i < len( text ) and ( text[ i ].isspace() or unicodedata.category( text[ i ] ) == "Cf" ):
        i += 1
    return text[ i: ]


def _prefix_looks_like_credential( prefix: str ) -> bool:
    """
    Decide on an already-read prefix. Split out so the decision is testable without
    a filesystem, and so `is_credential_file` holds only the fail-closed IO.

    Requires:
        - prefix is decoded text, possibly TRUNCATED mid-token

    Ensures:
        - True on a PEM private-key header, which needs no parsing
        - True on a parseable JSON value carrying a credential type or field AT ANY
          DEPTH, inside objects or arrays
        - True when the prefix is a TRUNCATED JSON container that already shows a
          credential field — a key does not become safe because the read stopped
          early, which is the same fail-closed rule applied to truncation
        - False for an empty prefix, which carries no signature to act on

    Raises:
        - nothing
    """
    if not prefix:
        return False

    # 🔴 STRIP THE BOM BEFORE ANYTHING LOOKS AT THE TEXT. A UTF-8 byte-order mark
    # read under encoding="utf-8" arrives as a literal ﻿ character, and it is
    # NOT whitespace — `"﻿".isspace()` is False — so `lstrip()` leaves it in
    # place. That defeated BOTH branches at once: `json.loads` raised on the leading
    # mark, and the `startswith("{")` narrowing then said "this is prose, serve it".
    #
    # MEASURED before the fix: a BOM-prefixed ADC credential (refresh_token +
    # client_secret) and a service-account key whose private_key carries no PEM
    # header were both SERVED. The PEM shape still blocked, which is why this hid —
    # the fixture that would have caught it had a PEM header doing the work.
    # (Found by Tiffany on review of my own brace narrowing, which introduced it.)
    #
    # 🔴 SECOND PASS (Tiffany, review of the fix above): stripping the mark at
    # position 0 only closed 4 of the 12 shapes that were serving. A space, tab or
    # newline in FRONT of the mark shielded it — the whitespace lstrip() down at the
    # narrowing runs LATER, so the mark was back at the front by the time the brace
    # test looked. U+200B walked through untouched. Measured: 8 of 24 shapes still
    # SERVED a complete ADC credential at ff6c9e46. Both call sites now go through
    # the class-based strip, which is order-independent.
    prefix = _strip_leadin_noise( prefix )

    # PEM first: decisive, needs no parsing, catches a key pasted into any wrapper.
    if _PEM_PRIVATE_KEY.search( prefix ):
        return True

    try:
        parsed = json.loads( prefix )
    except ( ValueError, TypeError ):
        # TRUNCATED or non-JSON. A service-account key longer than the sniff window
        # lands here, so falling through to "serve it" would defeat the bounded read.
        #
        # ⚠️ ONLY for text that is TRYING to be a JSON container. Scanning arbitrary
        # prose for these strings blocks documentation ABOUT credentials — an auth
        # guide quoting `"type": "service_account"` is a document, and this test file
        # itself would be refused. A truncated key still starts with `{` or `[`;
        # prose does not, so the opening bracket is what separates them.
        if _strip_leadin_noise( prefix )[ : 1 ] not in _JSON_CONTAINER_OPENERS:
            return False

        # Put JSON escapes back before scanning. This branch reads RAW TEXT, so a key
        # written `"refresh_token"` is the same key to a parser and a different
        # string to a substring scan — which is exactly how one walked through.
        lowered = _decode_json_unicode_escapes( prefix ).lower()
        if any( f'"{key}"' in lowered for key in _CREDENTIAL_JSON_KEYS ):
            return True
        return any( f'"{value}"' in lowered for value in _CREDENTIAL_TYPE_VALUES )

    return _parsed_value_carries_a_credential( parsed )


def _decode_json_unicode_escapes( text: str ) -> str:
    """
    Return `text` with every `\\uXXXX` escape replaced by the character it names.

    Requires:
        - text is decoded text, possibly truncated mid-token

    Ensures:
        - returns text with each \\uXXXX escape replaced by chr( XXXX )
        - returns text unchanged when it carries no such escape

    Raises:
        - nothing
    """
    return _JSON_UNICODE_ESCAPE.sub( lambda match: chr( int( match.group( 1 ), 16 ) ), text )


def _value_is_secret_material( value ) -> bool:
    """
    Return True iff `value` is a real secret string rather than a schema or a
    template.

    THE TRADE THIS ENCODES, decided deliberately rather than discovered later: once
    the search goes to any depth, a bare key NAME stops being enough to refuse on. An
    OpenAPI spec names `client_secret` under `securitySchemes` and a template shows
    `"client_secret": "<yours>"` — both are documents, and both would be refused by a
    name-only rule the moment it stopped looking only at the top level. A credential
    carries the secret AS A STRING; a schema carries an object, and a template carries
    a placeholder.

    Requires:
        - nothing; any parsed JSON value is acceptable

    Ensures:
        - True only for a non-blank string that is not a syntactic placeholder
        - False for objects, arrays, numbers, booleans and null

    Raises:
        - nothing
    """
    if not isinstance( value, str ):
        return False
    if not value.strip():
        return False

    return _PLACEHOLDER_VALUE.match( value ) is None


def _object_declares_a_credential( node: dict ) -> bool:
    """
    Return True iff this ONE object is itself credential material.

    Requires:
        - node is a parsed JSON object

    Ensures:
        - True when its `type` names a credential type value
        - True when it carries a credential key holding secret material
        - False otherwise

    Raises:
        - nothing
    """
    declared_type = node.get( "type" )
    if isinstance( declared_type, str ) and declared_type.strip() in _CREDENTIAL_TYPE_VALUES:
        return True

    return any( _credential_field_carries_secret_material( node.get( key ) )
                for key in _CREDENTIAL_JSON_KEYS )


def _credential_field_carries_secret_material( value ) -> bool:
    """
    Return True iff a credential FIELD's value carries secret material, whether it
    holds the secret directly or holds a LIST of secret lines.

    WHY THE LIST ARM EXISTS (bug 0cbf69c0, found by Tiffany reviewing the depth fix):
    `_value_is_secret_material` answers about ONE value and correctly says no to a
    list, because a list is not a string. The walk then descends into the list's
    ITEMS — but they are strings, not objects, so nothing ever tests them. A key
    written as an array of PEM-less lines fell straight between the two, and with no
    `type` field to catch it the file was SERVED.

    Placeholder discrimination is kept, item by item: a list of `<your key here>`
    lines is still a template, and templates are documents.

    Requires:
        - nothing; any parsed JSON value is acceptable, including None for a key the
          object does not carry

    Ensures:
        - True for a real non-placeholder secret string
        - True for a list holding at least one such string, at any list depth
        - False for objects, numbers, booleans, null, and lists of placeholders

    Raises:
        - nothing
    """
    pending = [ value ]
    while pending:
        item = pending.pop()
        if isinstance( item, list ):
            # An explicit stack, like the walk above: list depth comes from the file,
            # so recursion here would put the interpreter's stack in a file's hands.
            pending.extend( item )
        elif _value_is_secret_material( item ):
            return True

    return False


def _parsed_value_carries_a_credential( parsed ) -> bool:
    """
    Return True iff a credential object sits ANYWHERE in the parsed value.

    🔴 THE DEPTH FIX. The previous check read `key in parsed` on the top-level object
    only, so six shapes walked through — the first of them being the client_secret
    JSON the GCP console hands you, which puts every field one level down under
    `"installed"` or `"web"`. Arrays were served outright. Nesting is not an attack
    here so much as the NORMAL shape of a downloaded credential.

    Walks with an explicit stack rather than recursion, so nesting depth is bounded by
    the file, not by the interpreter's stack — no depth cap to tune, and no crash on a
    deeply nested document.

    🔴 THE PAYLOAD FIX (bug b17ffefd). The walk crossed objects and arrays and STOPPED
    AT A STRING, so a whole credential carried as JSON TEXT inside another JSON file
    was never opened: `{"google_credentials": "{\\"type\\": \\"service_account\\", ...}"}`
    was served. That is the ordinary shape of terraform tfvars, a kubernetes secret and
    a compose env file — the credential is a string as far as the outer document is
    concerned, and a real key as far as anything reading it is concerned. A string that
    opens a JSON container is now re-parsed and pushed back onto the stack, up to
    CREDENTIAL_MAX_NESTED_PARSES times per file.

    Requires:
        - parsed is a value returned by json.loads

    Ensures:
        - True iff some object inside it satisfies _object_declares_a_credential,
          including objects recovered from JSON carried inside a string
        - False for scalars, which carry no fields to test

    Raises:
        - nothing
    """
    pending       = [ parsed ]
    reparses_left = CREDENTIAL_MAX_NESTED_PARSES

    while pending:
        node = pending.pop()
        if isinstance( node, dict ):
            if _object_declares_a_credential( node ):
                return True
            pending.extend( node.values() )
        elif isinstance( node, list ):
            pending.extend( node )
        elif isinstance( node, str ) and reparses_left > 0 and _opens_a_json_container( node ):
            reparses_left -= 1
            carried = _json_carried_in_a_string( node )
            if carried is not None:
                pending.append( carried )

    return False


def _opens_a_json_container( text: str ) -> bool:
    """
    Return True iff `text` starts a JSON object or array once the invisible lead-in is
    gone. The cheap test that decides whether a parse is worth attempting at all.

    Requires:
        - text is decoded text, possibly empty

    Ensures:
        - True only when the first visible character is `{` or `[`

    Raises:
        - nothing
    """
    return _strip_leadin_noise( text )[ : 1 ] in _JSON_CONTAINER_OPENERS


def _json_carried_in_a_string( text: str ) -> object:
    """
    Return the value parsed out of a string that carries JSON, or None when it does
    not parse.

    None means "there is nothing here to walk". A string that looked like a container
    and did not parse is text — it carries no object for the field test to read, and
    guessing at it would be the raw-substring scan the parsed path exists to avoid.

    Requires:
        - text is a string whose first visible character opens a JSON container

    Ensures:
        - returns the parsed value on success
        - returns None when the text is not parseable JSON

    Raises:
        - nothing
    """
    try:
        return json.loads( text )
    except ( ValueError, TypeError ):
        return None


def _is_secrets_path( relative_path: str ) -> bool:
    """
    Return True iff any path segment matches a SECRETS_BLOCKLIST_PATTERNS entry.

    Requires:
        - relative_path is a non-empty project-relative path string with no
          leading slash. Forward-slash separators only (POSIX-style).

    Ensures:
        - returns True if any segment of `relative_path` matches any blocklist
          pattern (basename AND any intermediate directory name are checked)
        - returns False otherwise
        - empty input returns False (cheap guard for callers)
    """
    if not relative_path:
        return False

    for part in relative_path.split( "/" ):
        if not part:
            continue
        for pattern in SECRETS_BLOCKLIST_PATTERNS:
            if pattern.search( part ):
                return True
    return False


# ---------------------------------------------------------------------------
# Whitelist + path resolution per scope
# ---------------------------------------------------------------------------

def _is_whitelisted_in_scope( scope_cfg: ScopeConfig, relative_path: str ) -> bool:
    """
    Return True iff `relative_path` is permitted by the scope's whitelist.

    Resolution order (Phase 3 manifest extension):
        1. If `scope_cfg.manifest` is set, the manifest's `allowed_prefixes` +
           `allowed_root_files` is the authority for this scope. Empty manifest
           lists mean "no paths permitted" (explicit-opt-in semantics).
        2. If no manifest, fall back to the INI-derived
           `scope_cfg.allowed_prefixes`. Empty → wildcard (per Q2-C
           missing-manifest semantics).
        3. Bare scope-root listing (empty relative_path) is always allowed so
           directory listings work.

    Requires:
        - scope_cfg is a ScopeConfig instance
        - relative_path is a project-relative path string with no leading slash

    Ensures:
        - returns True when the path passes the active whitelist (manifest or
          INI prefixes), False otherwise
        - empty relative_path returns True (root listing affordance)
    """
    if not relative_path:
        return True

    # Manifest authority (Q2-C / Q3-A): when present, use it.
    if scope_cfg.manifest is not None:
        m = scope_cfg.manifest
        # Root-file whitelist: exact-match check (only for top-level files).
        if "/" not in relative_path and relative_path in m.allowed_root_files:
            return True
        # Prefix whitelist
        for prefix in m.allowed_prefixes:
            if relative_path.startswith( prefix ):
                return True
            if relative_path == prefix.rstrip( "/" ):
                return True
        return False

    # No manifest — INI-derived behavior (wildcard if empty).
    if not scope_cfg.allowed_prefixes:
        return True
    for prefix in scope_cfg.allowed_prefixes:
        if relative_path.startswith( prefix ):
            return True
        if relative_path == prefix.rstrip( "/" ):
            return True
    return False


def _is_secrets_path_for_scope( scope_cfg: ScopeConfig, relative_path: str ) -> bool:
    """
    Combined floor + per-scope extra blocklist check.

    The universal floor (`SECRETS_BLOCKLIST_PATTERNS`) is checked first. If
    no floor pattern matches, the scope's `extra_blocklist_patterns` (from
    `manifest.extra_blocklist`, if any) are checked. Per Q4-B repos can only
    ADD patterns; they cannot remove floor patterns.
    """
    if _is_secrets_path( relative_path ):
        return True

    if not scope_cfg.extra_blocklist_patterns:
        return False

    for part in relative_path.split( "/" ):
        if not part:
            continue
        for pattern in scope_cfg.extra_blocklist_patterns:
            if pattern.search( part ):
                return True
    return False


def resolve_in_scope( scope_cfg: ScopeConfig, decoded_path: str ) -> str:
    """
    Resolve `decoded_path` against `scope_cfg.root`, blocking directory traversal.

    Requires:
        - scope_cfg is a ScopeConfig instance whose `root` is an absolute path
        - decoded_path is a URL-decoded relative path (no leading slash); may be ""

    Ensures:
        - returns an absolute filesystem path under (or equal to) scope_cfg.root
        - raises ValueError if normalized path escapes scope_cfg.root

    Raises:
        - ValueError when the resolved path would escape the scope root
    """
    full_path = os.path.normpath( os.path.join( scope_cfg.root, decoded_path ) )
    root      = scope_cfg.root.rstrip( os.sep )

    if full_path != root and not full_path.startswith( root + os.sep ):
        raise ValueError( f"Path escapes scope root: {decoded_path!r} (scope={scope_cfg.name!r})" )
    return full_path


# ---------------------------------------------------------------------------
# Registry build — invoked once at FastAPI startup
# ---------------------------------------------------------------------------

_RESERVED_SCOPE_NAMES = ( "docs", "io" )


def build_scope_registry( config_mgr ) -> dict:
    """
    Read `external repos` INI block and return a name → ScopeConfig dict.

    Requires:
        - config_mgr is a ConfigurationManager instance with the `external repos`
          key registered (default `[]` is OK — empty registry is legal)

    Ensures:
        - returns dict[str, ScopeConfig]
        - skips scopes whose name collides with built-ins (`docs`, `io`); logs warning
        - skips scopes whose `path` value is missing or does not exist on disk;
          logs warning (so an environment without a particular repo mounted doesn't
          fail startup)
        - prefixes are stripped of surrounding whitespace; empty prefix strings drop out
        - the dict is intended to be process-lifetime constant after startup

    Raises:
        - None — all failure modes are non-fatal warnings (registry build never
          aborts boot)
    """
    names = config_mgr.get( "external repos", default=[], return_type="list-string" )
    registry: dict = { }

    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue

        if name in _RESERVED_SCOPE_NAMES:
            print( f"[scope_registry] WARNING: external repo name {name!r} collides with built-in scope; skipping" )
            continue

        try:
            root = config_mgr.get( f"external repo {name} path", default=None, silent=True )
        except Exception:
            root = None

        if not root or not os.path.isdir( root ):
            print( f"[scope_registry] WARNING: external repo {name!r}: path {root!r} not found on disk; skipping" )
            continue

        try:
            prefixes_raw = config_mgr.get(
                f"external repo {name} allowed prefixes",
                default        = [ ],
                return_type    = "list-string",
                silent         = True,
            )
        except Exception:
            prefixes_raw = [ ]

        prefixes = tuple( p.strip() for p in prefixes_raw if p and p.strip() )

        # Phase 3: load `<root>/.docview.yml` if present. Failures fall back
        # to None (caller treats None as wildcard per Q2-C).
        manifest = load_manifest_for_scope( root )

        extra_blocklist_patterns: tuple
        if manifest is not None and manifest.extra_blocklist:
            extra_blocklist_patterns = tuple(
                re.compile( pat ) for pat in manifest.extra_blocklist
            )
        else:
            extra_blocklist_patterns = ()

        registry[ name ] = ScopeConfig(
            name                     = name,
            root                     = root,
            allowed_prefixes         = prefixes,
            manifest                 = manifest,
            extra_blocklist_patterns = extra_blocklist_patterns,
        )

    print( f"[scope_registry] registered {len( registry )} external scope(s): {sorted( registry )}" )
    return registry


# ---------------------------------------------------------------------------
# Inline smoke test — runs against the local INI when invoked directly
# ---------------------------------------------------------------------------

def quick_smoke_test():
    du.print_banner( "_scope_registry smoke test", prepend_nl=True )

    # 1) ScopeConfig is frozen
    try:
        sc = ScopeConfig( name="x", root="/tmp", allowed_prefixes=( ) )
        try:
            sc.name = "y"          # type: ignore[misc]
            print( "✗ ScopeConfig should be frozen but allowed mutation" )
        except Exception:
            print( "✓ ScopeConfig is frozen" )
    except Exception as e:
        print( f"✗ ScopeConfig construction failed: {e}" )

    # 2) Secrets blocklist
    blocked = [
        ".env", ".env.production", ".env.local",
        "credentials.json", "secrets.yaml",
        "id_rsa", "id_rsa.pub", "id_ed25519",
        "sub/dir/credentials.json",
        ".netrc", ".pgpass",
        "deploy.pem", "tls.key",
    ]
    allowed = [
        "environment.md", "environments.py",
        "pem-helper.py", "key_values.txt",
        "secretive_methods.py", "credentialism.txt",
        "src/rnd/foo.md",
    ]
    failures = 0
    for p in blocked:
        if not _is_secrets_path( p ):
            print( f"✗ _is_secrets_path missed: {p!r}" )
            failures += 1
    for p in allowed:
        if _is_secrets_path( p ):
            print( f"✗ _is_secrets_path false positive: {p!r}" )
            failures += 1
    print( f"{'✓' if failures == 0 else '✗'} secrets blocklist: {failures} failure(s)" )

    # 3) Whitelist semantics
    wild = ScopeConfig( name="wild", root="/tmp", allowed_prefixes=( ) )
    strict = ScopeConfig( name="s", root="/tmp", allowed_prefixes=( "src/", "docs/" ) )
    ok = True
    ok &= _is_whitelisted_in_scope( wild,   "anything/at/all.md" )
    ok &= _is_whitelisted_in_scope( wild,   "" )
    ok &= _is_whitelisted_in_scope( strict, "src/foo.py" )
    ok &= _is_whitelisted_in_scope( strict, "src" )
    ok &= _is_whitelisted_in_scope( strict, "" )
    ok &= not _is_whitelisted_in_scope( strict, "lib/foo.py" )
    ok &= not _is_whitelisted_in_scope( strict, "lib" )
    print( f"{'✓' if ok else '✗'} whitelist semantics" )

    # 4) Path traversal block
    try:
        resolve_in_scope( strict, "../etc/passwd" )
        print( "✗ resolve_in_scope failed to block traversal" )
    except ValueError:
        print( "✓ resolve_in_scope blocks traversal" )

    du.print_banner( "_scope_registry smoke test complete", prepend_nl=True )


if __name__ == "__main__":
    quick_smoke_test()
