---
capability: duplicate-check-proof-plant
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.duplicate_check.proof.plant.banned_names@12c8eabefe
  - cosa.repo.duplicate_check.proof.plant.check_rewrite@c68566a93b
  - cosa.repo.duplicate_check.proof.plant.plant_rewrite@a52df8d9fa
  - cosa.repo.duplicate_check.proof.plant.python_forbidden@10ebf799fc
  - cosa.repo.duplicate_check.proof.plant.python_need@428d5b7db7
  - cosa.repo.duplicate_check.proof.plant.python_shape@86fed15a2b
  - cosa.repo.duplicate_check.proof.plant.rewrite_prompt@d16769ba46
  - cosa.repo.duplicate_check.proof.plant.select_originals@2294552d55
  - cosa.repo.duplicate_check.proof.plant.strip_names@3e2cd64088
  - cosa.repo.duplicate_check.proof.proof_bar.agreement@718a92c728
  - cosa.repo.duplicate_check.proof.proof_bar.evaluate_bar@eedeac19fb
  - cosa.repo.duplicate_check.proof.proof_bar.stratum_rates@bd34ca44cf
---
# Duplicate checker proof: planting and the bar
The proof shows the checker finds planted and real duplicates. A planted duplicate is a rewrite of an original that must pass its checks.
- `select_originals` draws the definitions to rewrite, with a fixed share of script definitions.
- `python_need` builds the stripped need input of a Python definition. `python_forbidden` is its forbidden list, longest first, and with `banned_names` it lists the words a rewrite may not contain. `strip_names` replaces declared names by placeholders, longest first.
- `rewrite_prompt` builds the prompt that asks for a rewrite. `python_shape` returns the shingle set of the first function in Python source, or None.
- `check_rewrite` judges a rewrite against its original. `plant_rewrite` asks until one passes or the tries run out.
- `evaluate_bar` compares the three proof figures with their bars, using exact fractions.
- `agreement` counts how often two passes over the same pairs give the same flag. `stratum_rates` reports each stratum's found rate with its interval.
- The run itself is on [[duplicate-check-proof-run]].
