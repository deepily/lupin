---
capability: repo-tools-candidate-purpose-lines
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.candidates.purpose_lines.prompt_hash@b1400b5db7
  - cosa.repo.symindex.candidates.purpose_lines.default_screen@e2d75b75f7
  - cosa.repo.symindex.candidates.purpose_lines.load_lines@0b7ddaec71
  - cosa.repo.symindex.candidates.purpose_lines.judge_purpose@3442c440e7
  - cosa.repo.symindex.candidates.purpose_lines.write_purpose_lines@49caa2c5e0
---
# Candidate purpose lines

A purpose line is one sentence that says what an index entry is for. The writer is asked for at most 25 words, starting with a verb. It is written once per pin by a bounded Claude Code job and never regenerated on read. The prose index and the prose vectors use it.

## Store
- Rows are JSON lines in `purpose.jsonl`: `pin`, `purpose`, `prompt_hash` and `writer_version`.
- `load_lines( store_path )` returns `{ pin: row }`. A missing file is `{}` and the first row for a pin wins.
- `prompt_hash()` is the first 16 hex characters of the sha256 of the prompt text, so a prompt change is visible in every row.

## Writing
- `write_purpose_lines( entries, writer, store_path, writer_version, screen, batch_size=25 )` sends only entries that pass the sendable screen and have no stored line. The writer receives ids only, never source text. It returns `written`, `kept`, `dropped_screen`, `dropped_output` and `missing`. Stored rows are never rewritten; a changed pin gets a new row.
- `judge_purpose( purpose, hits )` returns None for an acceptable line, else `not_text`, `empty`, `too_long` (over 25 words) or `screen:<kinds>`. The verb start is not checked. A rejected line is listed, never stored.
- `default_screen()` returns the index's own `sendable` and `c1_hits` from `lupin_mcp.reuse_tools`, imported on first use.
