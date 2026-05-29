import datetime as dt
from typing import Optional

class Stopwatch:
    """
    A simple stopwatch utility for timing code execution.
    
    This class provides timing functionality with optional printing
    of elapsed time in various formats.
    """
    
    def __init__( self, msg: Optional[str]=None, silent: bool=False  ):
        """
        Initialize a new Stopwatch instance.
        
        Requires:
            - msg is None or a string message to display at start
            - silent is a boolean flag for output suppression
            
        Ensures:
            - Stores initial message and silent flag
            - Records start time as current datetime
            - Prints initial message if provided and not silent
        """
        # This is helpful for suppressing/halving output when it's essentially going to be reproduced later when a task is completed
        if msg and not silent: print( msg )
        
        self.init_msg   = msg
        self.silent     = silent
        self.start_time = dt.datetime.now()
        
    def __enter__( self ) -> 'Stopwatch':
        """
        Context manager entry point.
        
        Requires:
            - None
            
        Ensures:
            - Resets start time to current datetime
            - Returns self for context manager usage
        """
        self.start_time = dt.datetime.now()
        
        return self
    
    def __exit__( self, exc_type, exc_val, exc_tb ) -> None:
        """
        Context manager exit point.
        
        Requires:
            - Standard context manager exception parameters
            
        Ensures:
            - Records end time as current datetime
            - Calculates interval in milliseconds
            - Prints elapsed time unless silent
        """
        self.end_time = dt.datetime.now()
        self.interval = int( (self.end_time - self.start_time).total_seconds() * 1000 )
        
        if not self.silent:
            print( f"Done in [{self.interval:,}] ms" )
    
    def print( self, msg: Optional[str]=None, prepend_nl: bool=False, end: str="\n\n", use_millis: bool=False ) -> None:
        """
        Print time elapsed since instantiation.
        
        Requires:
            - msg is None or a string message to display
            - prepend_nl is a boolean for adding newline before output
            - end is a string to append at end of output
            - use_millis is a boolean for millisecond format
            
        Ensures:
            - Prints elapsed time with appropriate formatting
            - Uses mm:ss format if more than 59 seconds elapsed
            - Uses milliseconds if use_millis is True
            - Respects silent flag to suppress output
            - Combines init_msg with msg if both provided
            
        Notes:
            - If more than 1 minute has passed it uses "mm:ss" format
            - Otherwise, it just prints seconds
            - This is fairly simpleminded, it's probably more accurate to use timeit
        """
        
        seconds = (dt.datetime.now() - self.start_time).seconds
        
        # build msg argument
        if msg is None and self.init_msg is None:
            msg = "Finished"
        elif msg is None and self.init_msg is not None:
            msg = self.init_msg
        elif msg is not None and self.init_msg is not None:
            msg = self.init_msg + " " + msg
        
        # preformat output
        if prepend_nl and not self.silent: print()
        
        if use_millis:
            
            # From: https://stackoverflow.com/questions/766335/python-speed-testing-time-difference-milliseconds
            delta = dt.datetime.now() - self.start_time
            millis = int( delta.total_seconds() * 1000 )
            
            if not self.silent: print( "{0} in {1:,} ms".format( msg, millis ), end=end )
        
        elif seconds > 59:
            
            # From: https://stackoverflow.com/questions/775049/how-do-i-convert-seconds-to-hours-minutes-and-seconds
            minutes, seconds = divmod( seconds, 60 )
            if not self.silent: print( "{0} in {1:02d}:{2:02d}".format( msg, minutes, seconds ), end=end )
        
        else:
            if not self.silent: print( "{0} in {1:,} seconds".format( msg, seconds ), end=end )
    
    def get_delta_ms( self ) -> int:
        """
        Calculate the time delta in milliseconds.
        
        Requires:
            - Stopwatch instance has been initialized
            
        Ensures:
            - Returns elapsed time in milliseconds as integer
            - Updates end_time to current datetime
            - Stores elapsed_time and delta_ms as instance attributes
        """
        self.end_time     = dt.datetime.now()
        self.elapsed_time = self.end_time - self.start_time
        self.delta_ms     = int( self.elapsed_time.total_seconds() * 1000 )
        
        return self.delta_ms
    

if __name__ == '__main__':
    
    timer = Stopwatch()
    timer.print( "Finished doing foo" )
    timer.print( None )
    timer.print()


