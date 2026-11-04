---
capability: ts-code-and-export-scripts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - src.scripts.ts_code_tokens.isJavaScript@f4240df7da
  - src.scripts.ts_code_tokens.signature@5df62e47de
  - src.scripts.ts_code_tokens.codeTokens@58c25621df
  - src.scripts.ts_code_tokens.describe@ea55c41b03
  - src.scripts.ts_code_tokens.run@abf2a072c5
  - src.scripts.ts_export_extract.isExported@d04df31cdb
  - src.scripts.ts_export_extract.boundNames@7760db686b
  - src.scripts.ts_export_extract.declared@18a04b579f
  - src.scripts.ts_export_extract.isCommonjsTarget@4ba2c0b45c
  - src.scripts.ts_export_extract.commonjsAssignments@5147efd03c
  - src.scripts.ts_export_extract.exportsOf@a458aa2efb
  - src.scripts.ts_export_extract.exportsRecord@bb618a88d1
  - src.scripts.ts_export_extract.main@2799b87b01
---
# Script code token and export extractors
Two Node scripts under `src/scripts/` that build on the comment extractor ([[ts-doc-extract-script]]).
- `ts_code_tokens.mjs` prints a text's code tokens and the comments that tools read, for the docs-only check. A double slash in a string is never taken for a comment.
- `isJavaScript` is true for a name ending in `.js`, `.mjs` or `.cjs`.
- `signature` names a comment a tool reads. A banner or directive gives its text, and a doc block gives its tool-read words. Any other comment gives null.
- `codeTokens` lists the leaf tokens with a line break flag, and marks each tool-read comment with the number of tokens before it.
- `describe` gives one text's errors, tokens, marks, directives, typed tags and hashbang. `run` reads a JSON list of texts and writes one line each, returning 2 for bad input.
- `ts_export_extract.mjs` lists a script's exported top-level symbols and says which have a doc comment. `main` runs it over files and returns 2 for a bad call.
- `isExported` tests for the export keyword. `boundNames` lists the names a binding introduces. `declared` names a declaration, and an unnamed default is named default.
- `isCommonjsTarget` and `commonjsAssignments` find writes to `module.exports` or `exports.name`.
- `exportsOf` builds the symbol list and counts re-exports apart. `exportsRecord` returns the record for one source, parsed as the comment extractor parses it.
