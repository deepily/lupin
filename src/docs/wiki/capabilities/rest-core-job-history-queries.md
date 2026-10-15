---
capability: rest-core-job-history-queries
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.job_persistence.query_job_history@dfee7420b8
  - cosa.rest.job_persistence.get_job_by_id_hash@2509d130ed
  - cosa.rest.job_persistence.get_active_job_ids_by_user@a136c2d443
  - cosa.rest.job_persistence.get_checkpoint_for_job@4683f7e8a8
  - cosa.rest.job_persistence.get_original_args_for_job@e4f4cb35a0
  - cosa.rest.job_persistence.delete_job_history@6e6c54c870
  - cosa.rest.job_persistence.delete_job_history_bulk@d45245667b
  - cosa.rest.agentic_job_factory.create_agentic_job@66e3a9bf56
  - cosa.rest.agentic_job_factory.resume_job@6348efc82a
  - cosa.rest.job_history_cleanup.clean_job_history@28fba043ca
---
# Job history reads, deletes and job building

Reads and deletes on the `job_history` table, and the factory that turns a stored row back into a job. The writes are on [[rest-core-job-persistence-lifecycle]].

## History
- `query_job_history` filters by user, status, job type and a day window, with `limit` capped at 100 and `offset`. `exclude_ids` and `exclude_user_id` leave jobs out.
- `get_job_by_id_hash` returns one row as a dict or `None`. `get_active_job_ids_by_user` maps user to the ids of pending and running jobs, to rebuild the job tracker at startup.
- `get_checkpoint_for_job` returns the checkpoint only for a stalled job. `get_original_args_for_job` returns the original args, routing command, user, email and session.
- `delete_job_history( id_hash )` returns `True` when a row went. `delete_job_history_bulk( user_id, days )` deletes in one statement and returns the count. `user_id=None` is the admin form, and `days` matches rows created within the last N days. With both `None` it deletes every row.
- None of these raises. A failure gives `None` from the single-row reads and `False` from `delete_job_history`.
- It gives `{"jobs": [], "total": 0}` from `query_job_history`, `{}` from `get_active_job_ids_by_user` and `0` from the bulk delete.

## Building jobs
- `create_agentic_job( command, args_dict, user_id, user_email, session_id )` looks `command` up in the job registry. It returns the built job, or `None` when no entry owns it. A builder can raise `SubmitRefused` for bad input. A new command needs a builder, a `JOB_BUILDERS` entry and a registry listing.
- `resume_job( job_id_hash, args_overrides )` rebuilds a stalled job through that factory and attaches its checkpoint, with `resume_count` raised by one. It returns `None` with no checkpoint on a stalled row, no routing command or no built job. `args_overrides` merge into the original args, skipping `None` values.

## Test database
- `clean_job_history( conn )` locks the table, then deletes every row except pending ones scheduled in the future. A job scheduled on the test server survives a cleanup.
