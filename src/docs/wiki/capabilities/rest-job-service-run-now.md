---
capability: rest-job-service-run-now
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.rest.job_service.expand@631c5f17e9
  - cosa.rest.job_service.home_and_pip@4fa2e3db51
  - cosa.rest.job_service.paths_of@6a2f351cb1
  - cosa.rest.job_service.run_command@c6fb608f03
  - cosa.rest.job_service.bootstrap_env@af5e0ff32e
  - cosa.rest.job_service.run_now@dd6f2038fd
---
# Jobs service: Run now and run commands

Starts a registry job outside its schedule. It is the only management action the operator allowed. The assessing half is in [[rest-job-service-assessment]]; the registry is in [[rest-job-registry]].

## Building the command
- `expand` fills `{root}`, `{data}`, `{home}`, `{pip}`, `{deepily_data}` and `{python}` in a string, and inside lists and dicts.
- `home_and_pip` returns the home folder and the planning-is-prompting root from the environment, with defaults.
- `paths_of` returns the placeholder values for a run, adding the deepily data folder from the environment.
- `run_command` returns the argument list and the environment. The environment layers the base, the registry's default run settings, the job's own, then `LUPIN_JOB_TRIGGER`. Run now and the cron entry script both read the command from here.
- `bootstrap_env` picks the default run settings that do not name the data folders. So the process can find its data folder with no copy of them in the shell.

## Starting a run
- `run_now` returns a status and body. Unknown job is 404, a job with no run command is 422, and a held run lock is 409. Run now never queues behind a live run.
- Otherwise it starts the child in its own session with trigger `hand` and appends the output to the Run now log. It returns 200 with the process id and start time.
- A thread waits on the child so no zombie is left. The caller must already have proved the login is the operator's.
