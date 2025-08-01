import cosa.utils.util as du

def remove_line_numbers( path, write_back=True ):
    """
    Remove line numbers from a text file that uses "number. " formatting.
    
    Requires:
        - path must be a valid file path to existing text file
        - File must be readable and writable (if write_back=True)
        - Lines must follow "number. content" format
        
    Ensures:
        - Loads file content as list of lines
        - Removes line number prefix and extraneous quotes from each line
        - Displays first 5 processed lines for verification
        - Writes modified content back to file if write_back=True
        
    Args:
        path: File path to process
        write_back: If True, writes modified content back to file (default: True)
        
    Returns:
        None
        
    Raises:
        FileNotFoundError: If file does not exist
        IOError: If file cannot be read or written
        IndexError: If line format doesn't contain ". " separator
    """
    
    lines = du.get_file_as_list( path, clean=True )
    
    print( "Total number of lines: [{}]".format( len( lines ) ) )
    
    # This assumes "number dot space" formatting. removes extraneous double quotes too
    lines = [ line.split( ". " )[ 1 ].replace( '"', '' ) for line in lines ]
    
    for line in lines[ 0:5 ]:
        print( line )
    
    # Write lines back to the same file
    if write_back:
        du.write_lines_to_file( path, lines )

def remove_zero_length_strings( path ):
    """
    Remove empty lines from a text file.
    
    Requires:
        - path must be a valid file path to existing text file
        - File must be readable and writable
        - du utility functions must be available
        
    Ensures:
        - Loads file content as list of lines
        - Filters out all zero-length strings/empty lines
        - Reports before/after line counts
        - Writes filtered content back to original file
        
    Args:
        path: File path to process
        
    Returns:
        None
        
    Raises:
        FileNotFoundError: If file does not exist
        IOError: If file cannot be read or written
    """
    
    lines = du.get_file_as_list( path, clean=True )
    
    # Using list comprehension to test for and reject zero length strings
    print( " PRE: Total number of lines: [{}]".format( len( lines ) ) )
    lines = [ line for line in lines if len( line ) > 0 ]
    print( "POST: Total number of lines: [{}]".format( len( lines ) ) )
    
    # Write lines back to the same file
    du.write_lines_to_file( path, lines )

def get_agent_synonyms():
    """
    Get predefined dictionary of agent types and their synonyms.
    
    Requires:
        - No preconditions
        
    Ensures:
        - Returns dictionary with agent types as keys
        - Each value is a list of synonym strings for that agent type
        - Includes synonyms for receptionist, timekeeper, meteorologist, todo list, calendaring
        
    Args:
        None
        
    Returns:
        dict: Dictionary mapping agent types to lists of synonyms
        
    Raises:
        No exceptions raised
    """
    
    agent_synonyms = {
        "receptionist" : [ "receptionist", "front desk", "administrator", "secretary", "office assistant", "operator" ],
        "timekeeper"   : [ "timekeeper", "scheduler", "time manager", "clock watcher", "chronologist", "time coordinator" ],
        "meteorologist": [ "meteorologist", "weather forecaster", "climatologist", "weather scientist", "atmospheric scientist", "weatherman" ],
        "todo list"    : [ "todo list", "task manager", "list coordinator", "list organizer", "activity overseer", "duty administrator" ],
        "calendaring"  : [ "calendaring", "schedule manager", "date planner", "event organizer", "social secretary", "appointment scheduler" ]
    }
    return agent_synonyms

# Create main method
if __name__ == "__main__":
    
    # remove_zero_length_strings( path=du.get_project_root() + "/src/ephemera/prompts/data/synthetic-data-agent-routing-todo-lists.txt" )
    # remove_zero_length_strings( path=du.get_project_root() + "/src/ephemera/prompts/data/placeholders-cities-and-countries.txt")
    remove_zero_length_strings( path=du.get_project_root() + "/src/ephemera/prompts/data/placeholders-calendaring-places.txt" )
    
    # remove_line_numbers( path = du.get_project_root() + "/src/prompts/data/synthetic-data-search-in-current-tab.txt", write_back=True )
    # remove_line_numbers( path = du.get_project_root() + "/src/prompts/data/synthetic-data-search-google-in-current-tab.txt", write_back=True )
    # remove_line_numbers( path = du.get_project_root() + "/src/prompts/data/synthetic-data-search-google-scholar-in-current-tab.txt", write_back=True )
    # remove_line_numbers( path = du.get_project_root() + "/src/prompts/data/synthetic-data-search-in-new-tab.txt", write_back=True )
    # remove_line_numbers( path = du.get_project_root() + "/src/prompts/data/synthetic-data-search-google-in-new-tab.txt", write_back=True )
    # remove_line_numbers( path = du.get_project_root() + "/src/prompts/data/synthetic-data-search-google-scholar-in-new-tab.txt", write_back=True )
    # remove_line_numbers( path = du.get_project_root() + "/src/prompts/data/synthetic-data-none-of-the-above.txt", write_back=True )

    # pass