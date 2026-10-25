---
capability: semdup-blind-and-extract
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.semdup.blind.assert_blind@6a339fec90
  - cosa.repo.semdup.blind.blind_definition@e869f00c91
  - cosa.repo.semdup.blind.candidate_order@f1e6d8fe1a
  - cosa.repo.semdup.blind.opaque_id@a27114c110
  - cosa.repo.semdup.blind.relative_path@2d6d6b1b07
  - cosa.repo.semdup.blind.scrub_tokens@8f47aa59e9
  - cosa.repo.semdup.blind.strip_comment_lines@1add6a8e41
  - cosa.repo.semdup.errors.SemdupError@f68cfbaa39
  - cosa.repo.semdup.extract.completeness@67189ce729
  - cosa.repo.semdup.extract.definition_id@02d329f84e
  - cosa.repo.semdup.extract.extract_python@0fae25e2f4
  - cosa.repo.semdup.extract.extract_script@3ada0672cc
  - cosa.repo.semdup.extract.extract_tree@e9eefcff81
  - cosa.repo.semdup.blind.breaching_ids@1f7886bb36
---
# Duplicate checker: blinding and extraction
The semantic duplicate checker counts surplus copies a run wrote. This page covers what goes in: every definition, and the blinding of what the judge sees.
- `extract_tree` extracts every definition of the given files and accounts for what could not be read. `extract_python` and `extract_script` read one file kind each.
- `extract_python` includes nested and private definitions. `extract_script` takes the compiler's own node count.
- `completeness` refuses a partial extraction of script files. `definition_id` is `d-` and ten hex digits of a sha256.
- `blind_definition` returns what the judge may see of a definition. `opaque_id` replaces its id with `x-` and ten hex digits.
- `scrub_tokens` builds the list of reuse-tool tokens and arm labels. `strip_comment_lines` removes comment lines that hold one.
- `assert_blind` refuses text that still carries a scrub token. `relative_path` drops a worktree prefix.
- `breaching_ids` names the definitions that `blind_definition` would refuse, as sorted ids. It blinds nothing for use.
- `candidate_order` orders blinded definitions by the sha of their opaque ids, so position tells nothing.
- `SemdupError` names every failure by a code, so a caller never reads a message. See [[semdup-candidates]] and [[semdup-judge-and-pipeline]].
