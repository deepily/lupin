---
capability: util-csv-text
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.csv_text.split_csv@a4083fadf8
---
# Comma-separated list reader

`cosa.utils.csv_text.split_csv` is the one reading of a list that an operator types into an INI file, an environment variable or a flag. Spaces around an entry and empty entries are noise.

## Rules
- `split_csv( text )` returns the entries in order, each stripped, with empty entries dropped. `None` and an empty string give an empty list.
- `lower=True` lowercases each entry. Case is kept otherwise.
- Spaces inside an entry stay.
- The cosa, REST, arbiter and lifespan readers call it. The hook library keeps its own splits, because a hook must not import cosa.
