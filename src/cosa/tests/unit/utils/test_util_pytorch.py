"""
Unit tests for cosa.utils.util_pytorch.

GPU-adjacent helpers, exercised with FULLY MOCKED torch models and a mocked
torch.cuda surface — NO real GPU is touched (honoring the never-grab-GPU
mandate). Covers device-allocation printing, CPU-allocation detection, and
GPU-memory release across the model-None / cuda-available branches.
"""

import unittest
from unittest.mock import patch, MagicMock

import cosa.utils.util_pytorch as up


def _fake_param( device_type ):
    """A stand-in torch parameter whose .device.type is `device_type`."""
    param = MagicMock()
    param.device.type = device_type
    return param


def _fake_model( device_types ):
    """A stand-in nn.Module whose named_parameters() yields the given devices."""
    model = MagicMock()
    model.named_parameters.return_value = [
        ( f"layer.{i}", _fake_param( t ) ) for i, t in enumerate( device_types )
    ]
    return model


class TestPrintDeviceAllocation( unittest.TestCase ):
    """print_device_allocation() iterates parameters without raising."""

    def test_prints_each_parameter( self ):
        model = _fake_model( [ "cpu", "cuda" ] )
        up.print_device_allocation( model )
        model.named_parameters.assert_called_once()


class TestIsAllocatedToCpu( unittest.TestCase ):
    """is_allocated_to_cpu() returns True iff any parameter lives on CPU."""

    def test_true_when_any_cpu( self ):
        self.assertTrue( up.is_allocated_to_cpu( _fake_model( [ "cuda", "cpu" ] ) ) )

    def test_false_when_all_non_cpu( self ):
        self.assertFalse( up.is_allocated_to_cpu( _fake_model( [ "cuda", "cuda" ] ) ) )


class TestReleaseGpuMemory( unittest.TestCase ):
    """release_gpu_memory() — model-present vs. None, cuda-available branches."""

    def test_moves_model_and_empties_cache_when_cuda_available( self ):
        model = MagicMock()
        with patch.object( up.torch.cuda, "is_available", return_value=True ), \
             patch.object( up.torch.cuda, "empty_cache" ) as empty, \
             patch.object( up.torch, "device", return_value="cpu-device" ):
            up.release_gpu_memory( model )
        model.to.assert_called_once_with( "cpu-device" )
        empty.assert_called_once()

    def test_none_model_skips_move_and_no_cache_when_cuda_absent( self ):
        with patch.object( up.torch.cuda, "is_available", return_value=False ), \
             patch.object( up.torch.cuda, "empty_cache" ) as empty:
            up.release_gpu_memory( None )            # model None -> no .to(), no del
        empty.assert_not_called()


if __name__ == "__main__":
    unittest.main()
