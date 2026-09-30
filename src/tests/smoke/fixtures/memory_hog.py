"""
Allocate resident memory in bounded steps, for the memory-cap bind proof.

Run by `src/tests/smoke/test_memory_cap_binds.py` inside a transient systemd
scope carrying the LAUNCHER'S OWN memory flags, to prove those flags actually
kill on this box rather than merely being emitted.

HARD BOUND: never allocates past the megabyte count given on argv, so a cap
that fails to bind costs a few hundred megabytes and a second, not the box.

Prints SURVIVED when it reaches the bound — which is the FAILURE signal for the
test that runs it, because reaching the bound means the cap did not kill.

The allocation is a list of `bytearray`s rather than one big object: bytearray
is zero-filled at construction, so every page is touched and therefore resident
anonymous memory. `MemorySwapMax=0` bounds anon specifically, which is what
makes this the right shape to allocate — a sparse or file-backed allocation
would be reclaimed instead of killed and would prove nothing.
"""

import sys

STEP_MB = 16

# Printed on reaching the bound. The test asserts on this exact token, so it is
# named here rather than spelled twice.
SURVIVED_TOKEN = "SURVIVED"


def allocate( limit_mb, step_mb=STEP_MB ):
    """
    Allocate up to limit_mb of touched, resident anonymous memory.

    Requires:
        - limit_mb is a non-negative integer
        - step_mb is a positive integer

    Ensures:
        - returns the list of allocated buffers, so the caller holds the only
          reference and nothing is freed early by the garbage collector
        - allocates at most limit_mb megabytes, never more
    """

    allocated = []

    for _ in range( limit_mb // step_mb ):
        allocated.append( bytearray( step_mb * 1024 * 1024 ) )

    return allocated


def main( argv ):
    """
    Allocate the requested megabytes and report survival.

    Requires:
        - argv is a sequence whose first element parses as an integer count of
          megabytes to allocate

    Ensures:
        - prints SURVIVED_TOKEN and returns 0 if the process is still alive
          after reaching the bound
        - returns nothing at all when the cap binds, because the process is
          SIGKILLed mid-allocation — which is the outcome the caller wants
    """

    limit_mb  = int( argv[ 0 ] )
    allocated = allocate( limit_mb )

    # The buffers must still be referenced when the token is printed: freeing
    # them first would let the process shrink back under the cap and report
    # SURVIVED without ever having held the memory.
    print( SURVIVED_TOKEN, flush=True )
    del allocated

    return 0


if __name__ == "__main__":   # pragma: no cover - process entry point; exercised as a subprocess by test_memory_cap_binds.py

    sys.exit( main( sys.argv[ 1: ] ) )
