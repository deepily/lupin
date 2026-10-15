---
capability: repo-tools-symindex-need-writing
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.symindex.need_writer.Reply@cd90278f37
  - cosa.repo.symindex.need_writer.sdk_reply@3b0fcd9905
  - cosa.repo.symindex.need_writer.write_need@172377d471
  - cosa.repo.symindex.need_writer.run_members@cbd9ff2eda
  - cosa.repo.symindex.need_writer.redo_from_resend_list@6f981c06d9
  - cosa.repo.symindex.need_writer.sample_members@742b152665
  - cosa.repo.symindex.need_writer.needs_document@b3887afbe8
  - cosa.repo.symindex.need_writer.main@44b8a14078
---
# Need sentences: the writing run

Writes one need sentence per sampled member through a tools-off Claude Code call. Input and checks are on [[repo-tools-symindex-need-input]].

## One member
- `sdk_reply( prompt, system_prompt, model )` is a coroutine that makes one call through the Claude Agent SDK with an empty tool list. It uses the hermetic profile of the model transport. The default model is `claude-sonnet-5-5`. It returns a `Reply` with the text, session id, notional cost and token counts. It raises `RuntimeError` for an error result or a stream with no result.
- `write_need( need, reply_fn )` is a coroutine. It asks up to three times and retries on a form failure. A `RuntimeError` is recorded as a `call_error` attempt. The record holds `ok`, `need`, `job_id`, `rewrites`, every attempt and the summed cost and tokens; `need` is None when no attempt passed.

## The sample
- `sample_members( sample_path )` reads member ids from the frozen sample file's strata, in file order, and raises `ValueError` for none.
- `run_members` writes one `NNN-<member>.json` per member in the output folder and resumes over saved files. A member in `redo` is asked again. If it had a saved file, its `rewrites` rises by one. A duplicate id raises `ValueError`.
- `redo_from_resend_list( rows )` turns the checker's resend list into redo kinds and avoid words per member, renaming `identifier` to `own_identifier`. Avoid words are kept only for members that failed identifier.
- `needs_document( run_dir, member_ids, sample_sha256 )` assembles `{ format: reuse-e2e-needs-1, sample_sha256, needs }` and raises `ValueError` for a member with no file or no accepted need.

## Command line
- `python -m cosa.repo.symindex.need_writer --sample S --out D` with `--limit`, `--model`, `--max-attempts`, `--resend-list`, `--redo-file` (rows of `member` and `check`) and `--assemble PATH`. `--assemble` writes the needs document and makes no model call. Otherwise `main` returns 0 when every member has an accepted need, else 1.
