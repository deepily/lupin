import os
from typing import Optional

import cosa.utils.util as du

import pandas as pd


def cast_to_datetime( df: pd.DataFrame, debug: bool=False ) -> pd.DataFrame:
    """
    Cast object columns ending with '_date' to datetime type.
    
    Requires:
        - df is a valid pandas DataFrame
        - debug is a boolean flag
        
    Ensures:
        - Returns DataFrame with date columns converted to datetime type
        - Only converts object-type columns ending with '_date'
        - Preserves original column names and order
        - Non-date columns remain unchanged
    """
    date_columns = df.select_dtypes( include=[ object ] ).columns.tolist()
    
    for column in date_columns:
        if column.endswith( "_date" ):
            if pd.api.types.is_string_dtype( df[ column ] ):
                df[ column ] = pd.to_datetime( df[ column ] )
    
    # if debug:
    #     du.print_banner( "df.dtypes:", prepend_nl=True, end="\n" )
    #     print( df.dtypes )
        
    return df

def read_csv( path: str, *args, **kwargs ) -> 'DeepilyDataFrame':
    """
    Read a CSV file and return a DeepilyDataFrame object.
    
    Requires:
        - path is a valid file path string
        - CSV file exists at the specified path
        
    Ensures:
        - Returns a DeepilyDataFrame instance loaded from the CSV
        - Preserves the file path in the DeepilyDataFrame object
        - Passes through any additional args and kwargs to pandas read_csv
        
    Raises:
        - FileNotFoundError if path does not exist
        - ValueError if file cannot be parsed as CSV
    """
    ddf = DeepilyDataFrame.read_csv( path, *args, **kwargs )
    
    return ddf
    
class DeepilyDataFrame( pd.DataFrame ):
    """
    Extended pandas DataFrame that maintains file path information.
    
    This class extends pandas DataFrame to add path persistence capabilities,
    allowing DataFrames to remember their source file location for saving.
    """
    
    # Path attribute to store the file path
    _metadata = [ '_path' ]
    
    def __init__( self, *args, path: Optional[str]=None, **kwargs ):
        """
        Initialize a DeepilyDataFrame with optional path information.
        
        Requires:
            - path is None or a valid file path string
            - args and kwargs are valid pandas DataFrame constructor arguments
            
        Ensures:
            - Creates a DeepilyDataFrame instance
            - Stores the path attribute if provided
            - Inherits all pandas DataFrame functionality
        """
        super().__init__( *args, **kwargs )
        self._path = path
    
    @property
    def _constructor( self ) -> type:
        """
        Return the constructor for creating new instances.
        
        Requires:
            - None
            
        Ensures:
            - Returns DeepilyDataFrame class for proper type propagation
            - Ensures pandas operations return DeepilyDataFrame instances
        """
        # Informs pandas that any method that is supposed to return a data frame returns a deepily data frame instead
        return DeepilyDataFrame
    
    @classmethod
    def read_csv( cls, path: str, *args, **kwargs ) -> 'DeepilyDataFrame':
        """
        Read CSV file and create a DeepilyDataFrame instance.
        
        Requires:
            - path is a valid file path string to a CSV file
            - File exists and is readable
            
        Ensures:
            - Returns a DeepilyDataFrame with data from the CSV
            - Stores the original file path for future save operations
            - Sets index_col=None by default
            
        Raises:
            - FileNotFoundError if file doesn't exist
            - pandas parsing errors if CSV is malformed
        """
        data = pd.read_csv( path, index_col=None, *args, **kwargs )
        
        return cls( data=data, path=path )
    
    def save( self, path: Optional[str]=None ) -> str:
        """
        Save the DataFrame to CSV file with appropriate permissions.
        
        Requires:
            - path is None or a valid file path string ending with '.csv'
            - If path is None, self._path must be set
            
        Ensures:
            - Saves DataFrame to specified or original path
            - Sets file permissions to world read/write (0o666)
            - Returns the path where file was saved
            
        Raises:
            - ValueError if no path is specified or available
            - ValueError if path doesn't end with '.csv'
            - OSError if file cannot be written
        """
        # Save DataFrame to its original path or to a specified new path
        if path is None:
            if self._path is None:
                raise ValueError( "Path is not specified" )
            path = self._path
        
        if path.endswith( '.csv' ):
            self.to_csv( path, index=False )
        else:
            raise ValueError( "Unsupported file type" )
        
        # Set world read and write on this path
        os.chmod( path, 0o666 )
        
        return path
    
if __name__ == '__main__':
    
    # df = DeepilyDataFrame.read_csv( du.get_project_root() + "/src/conf/long-term-memory/events.csv" )
    df = read_csv( du.get_project_root() + "/src/conf/long-term-memory/todo.csv" )
    
    # print( type( df ))
    print( df.head() )
    
    # df = df.drop( index=[ 0, 1 ] )
    # print( df.head() )
    
    df.save()
    
    
