import cosa.utils.util as du

import gc
import torch
from typing import Optional

def print_device_allocation( model: torch.nn.Module ) -> None:
    """
    Print the device allocation for all model parameters.
    
    Requires:
        - model is a valid PyTorch model (torch.nn.Module)
        
    Ensures:
        - Prints each parameter name with its device allocation
        - Displays information with a banner header
        - Iterates through all named parameters in the model
    """
    du.print_banner( "Model device allocation" )
    for name, param in model.named_parameters():
       print( f"{name}: {param.device}" )

def is_allocated_to_cpu( model: torch.nn.Module ) -> bool:
    """
    Check if any model parameters are allocated to CPU.
    
    Requires:
        - model is a valid PyTorch model (torch.nn.Module)
        
    Ensures:
        - Returns True if any parameter is on CPU device
        - Returns False if all parameters are on non-CPU devices
        - Checks all named parameters in the model
    """
    # test to see if *any* parameter is stashed on the cpu
    for name, param in model.named_parameters():
        if param.device.type == "cpu": return True

    return False

def release_gpu_memory( model: Optional[torch.nn.Module] ) -> None:
    """
    Release GPU memory by moving model to CPU and clearing cache.
    
    Requires:
        - model is None or a valid PyTorch model
        - CUDA is available (for cache clearing)
        
    Ensures:
        - Model is moved to CPU device if provided
        - Garbage collection is triggered
        - CUDA cache is emptied if available
        
    Notes:
        - See: https://www.phind.com/search?cache=kh81ys0uelwxs8zpykdzv0d8
        - This function attempts to free GPU memory
        - Model parameter becomes None after function returns
    """
    if model is not None:
        model.to( torch.device( "cpu" ) )
        del model
    
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()