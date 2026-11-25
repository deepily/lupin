---
capability: answer-attrition-run
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.answer_attrition_table.measure_row@54b27899c5
  - scripts.answer_attrition_table.label_equality@50e08c76c7
  - scripts.answer_attrition_table.typed_denominators@281c956da7
  - scripts.answer_attrition_table.draft_summary@185a38e1bd
  - scripts.answer_attrition_table.measure@a3d226d830
  - scripts.answer_attrition_table.render_markdown@e074c9a03e
  - scripts.answer_attrition_table.run@7f025a4a37
  - scripts.answer_attrition_table.main@acea817512
---
# Answer attrition table: running it

How the attrition table measures its populations and writes its result. It writes a JSON result and a markdown receipt and nothing else. Reading is in [[answer-attrition-reading]] and the steps in [[answer-attrition-steps]].

## Measuring
- `measure_row` counts one answered row's units at every step.
- `measure` does that for a population. A stored value that is not a dict is counted and left out of every unit count.
- It adds `label_equality`, how each single-text card field compares with its card's labels, and `typed_denominators`, the typed text counted several ways.
- `draft_summary` counts the reveals before an answer and what the extractor would read from each stored draft.

## The run
- `run( archive_path, records_path, live_session )` measures two populations from the run 2 archive: its evaluation cards and all its answered rows.
- On the live database it measures the cards asked on or after 10 Sep 2026 and all answered rows. Either side can be skipped.
- `render_markdown` writes one table per population, headed by the run time and the git sha.
- `main` writes the files named by `--out-json` and `--out-md`, and prints the table.
