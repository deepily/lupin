---
capability: util-code-runner-and-dataframe
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.util_code_runner.initialize_code_response_dict@093e39df41
  - cosa.utils.util_code_runner.assemble_and_run_solution@88a30dccaf
  - cosa.utils.util_code_runner.test_assemble_and_run_solution@8f8e7a7e79
  - cosa.utils.util_pandas.DeepilyDataFrame@18fdea0333
  - cosa.utils.util_pandas.DeepilyDataFrame.read_csv@becff7fbd9
  - cosa.utils.util_pandas.DeepilyDataFrame.save@f0babe470e
  - cosa.utils.util_pandas.cast_to_datetime@fe485d1d93
  - cosa.utils.util_pandas.read_csv@b9abedb961
---
# Code runner and the path-keeping data frame

`util_code_runner` runs generated code in a subprocess. `util_pandas` holds a data frame that remembers its csv path.

## What it does
- `initialize_code_response_dict()` returns `{ "return_code": -1, "output": "No code run yet" }`.
- `assemble_and_run_solution( solution_code, example_code, path_to_df, ... )` adds imports and post-function code. It writes a uniquely named file under the configured code path and runs it with `python_runtime`.
- The run has a 60 second timeout, and the child's working directory is `<root>/io`.
- It returns the response dict with the child's return code. Output is stripped stdout, `ERROR executing code:` plus stderr, or `No results returned`.
- The generated file is always removed.
- On timeout it returns output None when `return_none_on_timeout` is True, and otherwise re-raises. `inject_bugs=True` first rewrites the code with the bug injector.
- `test_assemble_and_run_solution` runs a fixed birthday-dataframe solution through that pipeline. It asserts nothing.
- `DeepilyDataFrame` is a pandas frame with a `path`. `read_csv( path, ... )` on the class or module loads a csv with `index_col=None` and keeps the path.
- `save( path=None )` writes the csv without an index to the given or stored path, and runs `chmod 0o666`. `cast_to_datetime( df )` converts string columns whose name ends in `_date`.

## Don't
- Do not pass `index_col` to `read_csv`. The function already passes it, so the call raises `TypeError`.
- Do not call `save` on a frame with no path or a path not ending in `.csv`. Both raise `ValueError`.

## Invariants
- A frame derived from a loaded one is a `DeepilyDataFrame` through `_constructor`.
