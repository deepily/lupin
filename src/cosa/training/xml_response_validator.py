import pandas as pd
from xmlschema import XMLSchema

import cosa.utils.util as du
import cosa.utils.util_xml as dux

class XmlResponseValidator:
    """
    Validates XML responses and calculates performance metrics.
    
    Responsible for:
    - Validating XML structure
    - Comparing responses to expected outputs
    - Calculating accuracy metrics
    - Producing validation reports
    """
    
    def __init__( self, debug: bool=False, verbose: bool=False ) -> None:
        self.debug           = debug
        self.verbose         = verbose
        self._xml_schema     = self._get_xml_schema()
    
    def _get_xml_schema( self ) -> XMLSchema:
        """
        Creates the XML schema for validation.
        
        Requires:
            - None
        
        Ensures:
            - Returns valid XMLSchema object
            - Schema defines response structure
        """
        xsd_string = """
        <xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
          <xs:element name="response">
            <xs:complexType>
              <xs:sequence>
                <xs:element name="command" type="xs:string"/>
                <xs:element name="args" type="xs:string"/>
              </xs:sequence>
            </xs:complexType>
          </xs:element>
        </xs:schema>
        """
        
        return XMLSchema( xsd_string )
    
    def is_valid_xml( self, xml_str: str ) -> bool:
        """
        Checks if XML is valid according to schema.
        
        Requires:
            - xml_str is a string
        
        Ensures:
            - Returns True if valid XML
            - Returns False on any validation error
        """
        try:
            return self._xml_schema.is_valid( xml_str )
        except Exception:
            return False
    
    def contains_valid_xml_tag( self, xml_str: str, tag_name: str ) -> bool:
        """
        Checks if XML contains a specific tag.
        
        Requires:
            - xml_str is a string
            - tag_name is a non-empty string
        
        Ensures:
            - Returns True if tag exists
            - Returns False on any error
        """
        try:
            return f"<{tag_name}>" in xml_str and f"</{tag_name}>" in xml_str
        except Exception:
            return False
    
    def is_response_exact_match( self, response: str, answer: str ) -> bool:
        """
        Checks if response exactly matches expected answer.
        
        Requires:
            - response is a string
            - answer is a string
        
        Ensures:
            - Strips whitespace before comparison
            - Returns True if exact match
            - Returns False otherwise
        """
        # Remove white space outside XML tags
        response = dux.strip_all_white_space( response )
        answer   = dux.strip_all_white_space( answer )
        
        if self.debug and self.verbose:
            print( f"response: [{response}]" )
            print( f"  answer: [{answer}]" )
            
        return response == answer
    
    def contains_correct_response_values( self, response: str, answer: str ) -> bool:
        """
        Check if the most common formatting error (```xml) is hiding a correct <response>...</response>
        
        Requires:
            - response is a string
            - answer is a string
        
        Ensures:
            - Extracts response tag content
            - Compares extracted content to answer
            - Returns True if values match
        """
        response_tag = dux.get_xml_tag_and_value_by_name( response, "response", default_value="broken" )
        if response_tag == "broken":
            return False
        
        return self.is_response_exact_match( response_tag, answer )
    
    def tag_values_are_equal( self, response: str, answer: str, tag_name: str="command" ) -> bool:
        """
        Checks if a specific tag's value in response matches the value in answer.
        
        Requires:
            - response is a string
            - answer is a string
            - tag_name is a non-empty string
        
        Ensures:
            - Extracts tag values from both strings
            - Returns True if values match
            - Returns False if extraction fails
        """
        command_response = dux.get_value_by_xml_tag_name( response, tag_name, default_value="broken" )
        command_answer   = dux.get_value_by_xml_tag_name( answer, tag_name, default_value="broken" )
        
        return command_response != "broken" and command_answer != "broken" and command_response == command_answer
    
    def validate_responses( self, df: pd.DataFrame ) -> pd.DataFrame:
        """
        Validates responses in a dataframe.
        
        Requires:
            - df contains 'response' and 'output' columns
        
        Ensures:
            - Adds validation columns to DataFrame
            - Validates XML structure and content
            - Returns enhanced DataFrame
        """
        # Validate the structure and content of the xml response
        df["response_xml_is_valid"]       = df["response"].apply( lambda cell: self.is_valid_xml( cell ) )
        df["contains_response"]           = df["response"].apply( lambda cell: self.contains_valid_xml_tag( cell, "response" ) )
        df["contains_command"]            = df["response"].apply( lambda cell: self.contains_valid_xml_tag( cell, "command" ) )
        df["contains_args"]               = df["response"].apply( lambda cell: self.contains_valid_xml_tag( cell, "args" ) )
        df["response_is_exact"]           = df.apply( lambda row: self.is_response_exact_match( row["response"], row["output"] ), axis=1 )
        df["response_has_correct_values"] = df.apply( lambda row: self.contains_correct_response_values( row["response"], row["output"] ), axis=1 )
        df["command_is_correct"]          = df.apply( lambda row: self.tag_values_are_equal( row["response"], row["output"], tag_name="command" ), axis=1 )
        df["args_is_correct"]             = df.apply( lambda row: self.tag_values_are_equal( row["response"], row["output"], tag_name="args" ), axis=1 )
        
        return df
    
    def print_validation_stats( self, df: pd.DataFrame, title: str="Validation Stats" ) -> pd.DataFrame:
        """
        Prints validation statistics.
        
        Requires:
            - df contains validation columns
            - title is a string
        
        Ensures:
            - Prints overall statistics
            - Calculates per-command accuracy
            - Returns stats DataFrame
        """
        du.print_banner( title, prepend_nl=True )
        print( f"               Is valid xml {df.response_xml_is_valid.mean() * 100:.1f}%" )
        print( f"        Contains <response> {df.contains_response.mean() * 100:.1f}%" )
        print( f"         Contains <command> {df.contains_command.mean() * 100:.1f}%" )
        print( f"            Contains <args> {df.contains_args.mean() * 100:.1f}%" )
        print( f"          Response is exact {df.response_is_exact.mean() * 100:.1f}%" )
        print( f"Response has correct values {df.response_has_correct_values.mean() * 100:.1f}%" )
        print( f"         Command is correct {df.command_is_correct.mean() * 100:.1f}%" )
        print( f"            Args is correct {df.args_is_correct.mean() * 100:.1f}%" )
        
        # Calculate accuracy per command
        cols                = ["command", "response_is_exact"]
        stats_df           = df[cols].copy()
        stats_df           = stats_df.groupby( "command" )["response_is_exact"].agg( ["mean", "sum", "count"] ).reset_index()
        
        # Format the percentages
        stats_df["mean"]   = stats_df["mean"].apply( lambda cell: f"{cell * 100:.2f}%" )
        # Sorts by mean ascending: Remember it's now a string we're sorting
        stats_df           = stats_df.sort_values( "mean", ascending=False )
        # Since I can't delete the index and not affect the other values, I'll just set the index to an empty string
        stats_df.index     = [""] * stats_df.shape[0]

        du.print_banner( f"{title}: Accuracy per command", prepend_nl=True )
        print( stats_df )
        
        return stats_df
    
    def get_validation_stats( self, df: pd.DataFrame ) -> dict:
        """
        Get validation statistics as a dictionary.
        
        Requires:
            - df contains validation columns
        
        Ensures:
            - Calculates percentage statistics
            - Includes per-command metrics
            - Returns complete stats dictionary
        """
        stats = {
            "valid_xml_percent"        : df.response_xml_is_valid.mean() * 100,
            "contains_response_percent": df.contains_response.mean() * 100,
            "contains_command_percent" : df.contains_command.mean() * 100,
            "contains_args_percent"    : df.contains_args.mean() * 100,
            "response_exact_percent"   : df.response_is_exact.mean() * 100,
            "correct_values_percent"   : df.response_has_correct_values.mean() * 100,
            "command_correct_percent"  : df.command_is_correct.mean() * 100,
            "args_correct_percent"     : df.args_is_correct.mean() * 100,
        }
        
        # Add per-command statistics
        command_stats = df.groupby( "command" )["response_is_exact"].mean().to_dict()
        stats["per_command"] = {cmd: val * 100 for cmd, val in command_stats.items()}
        
        return stats
    
    def compare_validation_results( self, before_df: pd.DataFrame, after_df: pd.DataFrame, title: str="Validation Comparison" ) -> pd.DataFrame:
        """
        Compares validation results between two dataframes.
        
        Requires:
            - Both DataFrames contain validation columns
            - title is a string
        
        Ensures:
            - Calculates differences between metrics
            - Formats results as percentages
            - Returns comparison DataFrame
        """
        metrics = [
            "response_xml_is_valid", "contains_response", "contains_command",
            "contains_args", "response_is_exact", "response_has_correct_values",
            "command_is_correct", "args_is_correct"
        ]
        
        metric_names = [
            "Valid XML", "Contains <response>", "Contains <command>",
            "Contains <args>", "Exact response match", "Correct response values",
            "Command is correct", "Args are correct"
        ]
        
        before_vals = [before_df[m].mean() * 100 for m in metrics]
        after_vals = [after_df[m].mean() * 100 for m in metrics]
        diff_vals = [after - before for after, before in zip( after_vals, before_vals )]
        
        comparison_df = pd.DataFrame({
            "Metric": metric_names,
            "Before (%)": [f"{val:.1f}%" for val in before_vals],
            "After (%)": [f"{val:.1f}%" for val in after_vals],
            "Difference": [f"{'+' if val > 0 else ''}{val:.1f}%" for val in diff_vals]
        })
        
        du.print_banner( title, prepend_nl=True )
        print( comparison_df )
        
        return comparison_df