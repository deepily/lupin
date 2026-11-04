"""
How long a test may wait for its own job to reach the done queue.

The consumer takes one job at a time, so a job waits for every job ahead of it, whoever
submitted them. A fixed wait is right only when the queue is short. The budget is therefore
the number of jobs ahead, plus the test's own job, times a ceiling for one job.

`/api/busy` is unfiltered and needs no login, so it counts jobs from every user.
A queue so deep that its budget passes the cap fails the test at once and names the depth.
"""

import requests

# Measured: a cold job takes 7 to 9 s, in run ts-bf9fd99c on 2026-10-08. A warm job replays in
# about 1 s. 20 s is more than twice the slowest cold job seen. It is a ceiling, not a forecast:
# a waiter returns the moment its job is done, so a high ceiling costs nothing on a warm cache.
PER_JOB_CEILING_SECONDS = 20

# The file budget in tests/helpers/file_budget.py defaults to 15 minutes. This cap stays well under
# it, so a runaway queue fails here with its depth and not as a file timeout with no explanation.
MAX_BUDGET_SECONDS = 600

BUSY_PATH       = "/api/busy"
BUSY_TIMEOUT    = 10
DEPTH_SIGNALS   = ( "run_queue_size", "todo_queue_size" )


class QueueTooDeep( AssertionError ):
    """The jobs ahead need more time than the cap allows."""


def jobs_ahead( busy: dict ) -> int:
    """
    The number of jobs that will be taken before a job submitted now.

    Requires:
        - busy is the parsed body of GET /api/busy

    Ensures:
        - returns run_queue_size plus todo_queue_size

    Raises:
        - ValueError naming the field when a depth signal is missing or is not a count
    """
    total = 0
    for name in DEPTH_SIGNALS:
        value = busy.get( name )
        if isinstance( value, bool ) or not isinstance( value, int ) or value < 0:
            raise ValueError( f"/api/busy gave no usable {name}: {value!r}; the wait budget cannot be worked out" )
        total += value
    return total


def budget_for( ahead: int ) -> int:
    """
    The seconds a test may wait for one job with `ahead` jobs in front of it.

    Requires:
        - ahead is a non-negative int

    Ensures:
        - returns ( ahead + 1 ) * PER_JOB_CEILING_SECONDS when that is within the cap

    Raises:
        - ValueError when ahead is negative
        - QueueTooDeep, naming the depth, the budget it would need and the cap, when it is over the cap
    """
    if ahead < 0: raise ValueError( f"jobs ahead cannot be negative: {ahead}" )
    needed = ( ahead + 1 ) * PER_JOB_CEILING_SECONDS
    if needed > MAX_BUDGET_SECONDS:
        raise QueueTooDeep(
            f"{ahead} jobs are ahead of this test's job; waiting for them needs {needed}s "
            f"at {PER_JOB_CEILING_SECONDS}s each, over the {MAX_BUDGET_SECONDS}s cap"
        )
    return needed


def budget_before_submit( base_url: str ):
    """
    Read the queue depth; return ( jobs_ahead, budget_seconds ) for a job about to go in.

    Requires:
        - the server at base_url answers GET /api/busy

    Ensures:
        - returns the pair; the budget comes from budget_for

    Raises:
        - ValueError when a depth signal is missing
        - QueueTooDeep when the queue is deeper than the cap allows
    """
    response = requests.get( f"{base_url}{BUSY_PATH}", timeout=BUSY_TIMEOUT )
    assert response.status_code == 200, f"{BUSY_PATH} answered {response.status_code}: {response.text[ :200 ]}"
    ahead = jobs_ahead( response.json() )
    return ahead, budget_for( ahead )
