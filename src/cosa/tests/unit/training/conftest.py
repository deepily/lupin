"""
Conftest for the training unit tests: no unit test may touch the real GPU.

The GPU is in active development use. A unit test that reaches a real
torch.cuda call passes or fails with the GPU's mood ("CUDA error: out of memory").
The autouse fixture below makes any such call fail the same way every time.
"""

from unittest.mock import patch

import pytest

try:
    import torch
except ImportError:  # pragma: no cover -- no torch on this machine, so there is no real GPU to guard
    torch = None

GPU_TOUCH_MESSAGE = "unit test touched the real GPU"

# Every torch.cuda entry point the training code (or a library under it) calls.
GUARDED_CUDA_CALLS = (
    "device_count",
    "is_available",
    "is_bf16_supported",
    "empty_cache",
    "ipc_collect",
    "synchronize",
    "current_device",
    "set_device",
    "device",
    "get_device_name",
    "get_device_properties",
    "mem_get_info",
    "memory_allocated",
    "memory_reserved",
    "max_memory_allocated",
    "max_memory_reserved",
    "reset_peak_memory_stats",
)


def _raise_gpu_touch( *args, **kwargs ):
    """
    Stand-in for a real torch.cuda call.

    Requires:
        - nothing; accepts any arguments

    Ensures:
        - never returns

    Raises:
        - AssertionError with GPU_TOUCH_MESSAGE
    """
    raise AssertionError( GPU_TOUCH_MESSAGE )


@pytest.fixture( autouse=True )
def no_real_gpu_in_unit_tests():
    """
    Replace the real torch.cuda entry points with a call that fails loudly.

    Requires:
        - nothing; does nothing when torch is not installed

    Ensures:
        - while the test runs, each name in GUARDED_CUDA_CALLS on the real torch.cuda
          raises AssertionError( "unit test touched the real GPU" ), whatever the GPU is doing
        - the originals are restored afterwards
        - tests that patch the module-level torch name of the code under test are unaffected
    """
    if torch is None:  # pragma: no cover -- no torch on this machine
        yield
        return

    patchers = [
        patch.object( torch.cuda, name, side_effect=_raise_gpu_touch, create=True )
        for name in GUARDED_CUDA_CALLS
    ]
    for patcher in patchers: patcher.start()
    try:
        yield
    finally:
        for patcher in reversed( patchers ): patcher.stop()
