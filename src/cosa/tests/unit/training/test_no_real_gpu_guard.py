"""
Unit tests for the autouse guard in the training conftest.

Proves the guard fires: a real torch.cuda call from a unit test raises
"unit test touched the real GPU", whatever state the GPU is in. Without these
tests, deleting the fixture would leave the suite green.
"""

import pytest

torch = pytest.importorskip( "torch" )

from cosa.tests.unit.training.conftest import GPU_TOUCH_MESSAGE, GUARDED_CUDA_CALLS


@pytest.mark.parametrize( "name", GUARDED_CUDA_CALLS )
def test_every_guarded_cuda_call_raises_under_the_guard( name ):
    """
    Each guarded torch.cuda entry point fails loudly.

    Requires:
        - the autouse fixture no_real_gpu_in_unit_tests is active

    Ensures:
        - calling the real torch.cuda attribute raises AssertionError with GPU_TOUCH_MESSAGE
    """
    with pytest.raises( AssertionError, match=GPU_TOUCH_MESSAGE ):
        getattr( torch.cuda, name )()


def test_the_guard_message_is_the_agreed_text():
    """
    The message is the one the row names.

    Ensures:
        - GPU_TOUCH_MESSAGE is "unit test touched the real GPU"
    """
    assert GPU_TOUCH_MESSAGE == "unit test touched the real GPU"
