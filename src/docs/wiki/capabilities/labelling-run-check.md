---
capability: labelling-run-check
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.labelling.run_check.check_pair@aabc33fab4
  - cosa.repo.labelling.run_check.compare@9e671deea4
  - cosa.repo.labelling.run_check.first_function@bd0de7f738
  - cosa.repo.labelling.run_check.make_cases@8b2088fa63
  - cosa.repo.labelling.run_check.needs_environment@dc4b42fd09
  - cosa.repo.labelling.run_check.parameter_pools@029f233efe
  - cosa.repo.labelling.run_check.pool_for@ff0c83db2b
  - cosa.repo.labelling.run_check.run_side@618ddbad33
  - cosa.repo.labelling.run_check.sandbox_command@235f8ece6c
  - cosa.repo.labelling.run_check_child.clear_folder@246cb0a488
  - cosa.repo.labelling.run_check_child.folder_state@aabcb959ed
  - cosa.repo.labelling.run_check_child.limit_resources@d476e418d5
  - cosa.repo.labelling.run_check_child.main@e4c925fd52
  - cosa.repo.labelling.run_check_child.run_case@84d16b01d8
  - cosa.repo.labelling.run_check_child.run_request@2b0c377543
  - cosa.repo.labelling.run_check_child.settle@7068864d34
---
# Labelling: the run-check

Rules on a model-written work-alike by running it beside its original. The item format is in [[labelling-tools]]. The need-set side is in [[needset-final-set]]. Call sites are in [[labelling-call-sites]].

## What it does
- `check_pair` runs an original and its rewrite on the same generated inputs. It returns `{ route, status, reason, cases }`.
- The route is `accept` when every case agrees and `reject` when one differs. It is `person_check` when the check cannot run the pair.
- `compare` checks what each side returns or raises, the arguments it changed, what it printed and the files it left. A difference names the first case and field.
- `first_function` finds the definition on each side. `parameter_pools` and `pool_for` read the original's signature and give each parameter values to try.
- A method, an untyped parameter or an unknown type goes to a person. `make_cases` draws the cases from a seed.
- `needs_environment` spots a missing name, module or permission and sends that side to a person. So does an original that raises on every case, differs between runs or times out.
- `run_side` runs one definition in a child process. `sandbox_command` builds the bubblewrap command around it.
- `run_check_child` is the code inside the sandbox. `main` reads one request and `limit_resources` caps the child. `run_request` defines the function and `run_case` calls it on a copy of each input.
- `settle`, `folder_state` and `clear_folder` make the outcomes comparable.

## Don't
- Don't run without bubblewrap. `run_side` raises `SANDBOX_UNAVAILABLE`, and there is no fallback.
- Don't read `person_check` as a verdict. It means the check ruled nothing.
- Don't treat the sandbox as a defence against hostile code. It guards against mistakes in a model's output.
