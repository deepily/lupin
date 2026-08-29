#!/usr/bin/env python3
"""
Git-tracked line-count + composition analyzer for the Lupin repo.

Counts ONLY files reported by `git ls-files` (so .gitignored build output is
structurally impossible to include). Classifies every tracked file into exactly
one bucket, then reports tiered totals.
"""
import io as _io
import json
import os
import subprocess
import sys
import tokenize
from collections import defaultdict

REPO = "/mnt/DATA01/include/www.deepily.ai/projects/lupin"

# ---------------------------------------------------------------- extensions
BINARY_EXT = {
    "png", "jpg", "jpeg", "gif", "mp3", "wav", "wasm", "ttf", "otf", "db",
    "bin", "ico", "pdf", "woff", "woff2", "symbols", "backup-20251030",
}
DATA_EXT = { "csv", "jsonl", "tsv" }

LANG_BY_EXT = {
    "py": "Python", "ts": "TypeScript", "js": "JavaScript",
    "html": "HTML", "mako": "HTML", "css": "CSS",
    "md": "Markdown",
    "yml": "YAML/INI/config", "yaml": "YAML/INI/config",
    "ini": "YAML/INI/config", "toml": "YAML/INI/config",
    "json": "YAML/INI/config", "service": "YAML/INI/config",
    "example": "YAML/INI/config", "template": "YAML/INI/config",
    "xml": "YAML/INI/config", "map": "YAML/INI/config",
    "gitignore": "YAML/INI/config", "dockerignore": "YAML/INI/config",
    "gitleaksignore": "YAML/INI/config", "docview": "YAML/INI/config",
    "sql": "SQL",
    "sh": "Shell", "command": "Shell", "bt": "Shell",
    "tf": "Terraform/HCL", "hcl": "Terraform/HCL",
    "txt": "Plain text", "log": "Plain text", "patch": "Plain text",
    "frag": "GLSL", "ipynb": "Jupyter notebook",
    "lock": "Lockfile",
}


def lang_of(path):
    base = os.path.basename(path)
    if base.lower().startswith("dockerfile"):
        return "Dockerfile"
    if "." not in base:
        return "Other (no extension)"
    ext = base.rsplit(".", 1)[1].lower()
    return LANG_BY_EXT.get(ext, "Other")


def ext_of(path):
    base = os.path.basename(path)
    return base.rsplit(".", 1)[1].lower() if "." in base else ""


# ---------------------------------------------------------------- buckets
# Exclusion buckets are checked in order; first match wins.
EXCLUDE_RULES = [
    ("X1 Agent output (io/)",                    lambda p: p.startswith("io/")),
    ("X2 Flutter web build output (vendored)",   lambda p: p.startswith("src/lupin_app/static/lupin-mobile-test/")),
    ("X3 Vendored third-party JS",               lambda p: "/static/js/vendor/" in p or p.endswith(".min.js") or p.endswith(".min.css")),
    ("X4 Lockfiles",                             lambda p: p in ("package-lock.json", "uv.lock")),
    ("X5 Generated API docs (OpenAPI spec + rendered md)", lambda p: p.startswith("src/docs/fastapi/api.")),
    ("X9 Captured golden snapshots",             lambda p: "/fixtures/golden/" in p or ".golden." in p),
    ("X6 Ephemera (archived notebooks / prompt data)", lambda p: p.startswith("src/ephemera/")),
    ("X7 Binary assets",                         lambda p: ext_of(p) in BINARY_EXT),
    ("X8 Data files (csv/jsonl/tsv)",            lambda p: ext_of(p) in DATA_EXT),
]

DOC_PREFIXES = (
    "src/docs/", "src/cosa/docs/", ".claude/commands/", ".claude/skills/",
    "src/cosa/.claude/", "src/workflow/",
)
DOC_ROOT_FILES = { "README.md", "CHANGELOG.md", "CLAUDE.md", "CLAUDE.local.md",
                   "AUTH_REQUIREMENTS.md", "LICENSE" }
RND_PREFIXES = ( "src/rnd/", "src/cosa/rnd/", "history/", "src/cosa/history/",
                 "todo-history/" )
RND_ROOT_FILES = { "history.md", "TODO.md", "bug-fix-queue.md",
                   "src/cosa/history.md", "src/cosa/TODO.md" }


def is_test(p):
    b = os.path.basename(p)
    return (p.startswith("src/tests/") or "/tests/" in p
            or b.startswith("test_") or b.endswith("_test.py")
            or b.endswith(".test.ts") or b.endswith(".spec.ts")
            or p == "src/conftest.py" or b == "conftest.py")


def bucket_of(p):
    for name, fn in EXCLUDE_RULES:
        if fn(p):
            return name, True
    if p in RND_ROOT_FILES or p.startswith(RND_PREFIXES):
        return "C R&D / design / history docs", False
    if p in DOC_ROOT_FILES or p.startswith(DOC_PREFIXES):
        return "B Documentation", False
    # remaining .md files scattered in code dirs = documentation
    if p.endswith(".md"):
        return "B Documentation", False
    if is_test(p):
        return "A2 Tests", False
    return "A1 Application code + config", False


# ---------------------------------------------------------------- counters
def count_python(text):
    """Return (code, comment, docstring, blank) line counts."""
    lines = text.splitlines()
    n = len(lines)
    kind = ["code"] * n           # default; refined below
    blank = [not l.strip() for l in lines]
    marked = [None] * n
    try:
        toks = list(tokenize.generate_tokens(_io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # fall back: comment-prefix heuristic
        c = cm = b = 0
        for l in lines:
            s = l.strip()
            if not s: b += 1
            elif s.startswith("#"): cm += 1
            else: c += 1
        return c, cm, 0, b

    # find docstring tokens: a STRING token that is the whole logical statement
    prev_significant = tokenize.INDENT
    for tok in toks:
        ttype, tstr, start, end, _ = tok
        if ttype == tokenize.COMMENT:
            for i in range(start[0] - 1, end[0]):
                if marked[i] is None: marked[i] = "comment"
        elif ttype == tokenize.STRING:
            if prev_significant in (tokenize.INDENT, tokenize.DEDENT,
                                    tokenize.NEWLINE, tokenize.NL,
                                    tokenize.ENCODING):
                for i in range(start[0] - 1, end[0]):
                    marked[i] = "docstring"
        if ttype not in (tokenize.NL, tokenize.COMMENT):
            prev_significant = ttype

    code = comment = doc = b = 0
    for i in range(n):
        if blank[i] and marked[i] is None:
            b += 1
        elif marked[i] == "docstring":
            doc += 1
        elif marked[i] == "comment":
            comment += 1
        else:
            code += 1
    return code, comment, doc, b


def count_cstyle(text):
    """Line-based split for TS/JS/CSS. Returns (code, comment, doc, blank).

    'doc' = JSDoc/TSDoc block comments opening with /**.
    """
    code = comment = doc = blank = 0
    in_block = False
    block_is_doc = False
    for raw in text.splitlines():
        s = raw.strip()
        if in_block:
            (doc if block_is_doc else comment)
            if block_is_doc: doc += 1
            else: comment += 1
            if "*/" in s:
                in_block = False
            continue
        if not s:
            blank += 1
        elif s.startswith("//"):
            comment += 1
        elif s.startswith("/*"):
            block_is_doc = s.startswith("/**")
            if block_is_doc: doc += 1
            else: comment += 1
            if "*/" not in s[2:]:
                in_block = True
        else:
            code += 1
    return code, comment, doc, blank


def count_hash_style(text):
    code = comment = blank = 0
    for raw in text.splitlines():
        s = raw.strip()
        if not s: blank += 1
        elif s.startswith("#") or s.startswith(";") or s.startswith("--"): comment += 1
        else: code += 1
    return code, comment, 0, blank


def count_generic(text):
    lines = text.splitlines()
    blank = sum(1 for l in lines if not l.strip())
    return len(lines) - blank, 0, 0, blank


# ---------------------------------------------------------------- main
def main():
    os.chdir(REPO)
    files = subprocess.run(["git", "ls-files", "-z"], capture_output=True,
                           check=True).stdout.decode().split("\0")
    files = [f for f in files if f]

    rows = []
    for p in files:
        bucket, excluded = bucket_of(p)
        lang = lang_of(p)
        size = os.path.getsize(p) if os.path.exists(p) else 0
        total = code = comment = doc = blank = 0
        binary = ext_of(p) in BINARY_EXT
        if not binary and os.path.exists(p):
            try:
                text = open(p, "r", encoding="utf-8", errors="strict").read()
            except (UnicodeDecodeError, OSError):
                binary = True
                text = None
            if text is not None:
                total = len(text.splitlines())
                if lang == "Python":
                    code, comment, doc, blank = count_python(text)
                elif lang in ("TypeScript", "JavaScript", "CSS"):
                    code, comment, doc, blank = count_cstyle(text)
                elif lang in ("Shell", "YAML/INI/config", "Terraform/HCL", "Dockerfile", "SQL"):
                    code, comment, doc, blank = count_hash_style(text)
                else:
                    code, comment, doc, blank = count_generic(text)
        rows.append(dict(path=p, bucket=bucket, excluded=excluded, lang=lang,
                         total=total, code=code, comment=comment, doc=doc,
                         blank=blank, bytes=size, binary=binary))

    json.dump(rows, open(sys.argv[1], "w"))
    print(f"scanned {len(rows)} tracked files")


if __name__ == "__main__":
    main()
