import sys
import os
from typing import Optional

from huggingface_hub import snapshot_download, login

# make this a class called HuggingFaceDownloader
# with a method called download_model
# that takes a repo_id as an argument
class HuggingFaceDownloader:

    def __init__( self, token: Optional[str]=None ) -> None:
        """
        Initialize a new HuggingFaceDownloader instance.
        
        Requires:
            - token is either None or a valid Hugging Face API token string
            
        Ensures:
            - The token is stored for later authentication with Hugging Face
            - No network requests are made during initialization
            
        Raises:
            - No exceptions are raised during initialization
        """
        self.token = token

    def download_model( self, repo_id: str ) -> str:
        """
        Download a model from Hugging Face Hub.
        
        Requires:
            - repo_id is a valid Hugging Face repository identifier
            - self.token is a valid Hugging Face API token or None
            - HF_HOME environment variable is set to a valid directory path
            
        Ensures:
            - Authenticates with Hugging Face using the provided token
            - Downloads the model to the directory specified by HF_HOME
            - Returns the local path to the downloaded model files
            
        Raises:
            - Exception with error message if download fails
            - SystemExit(1) if an error occurs during the process
        """
        try:
            login( token=self.token )
            local_path = snapshot_download( repo_id=repo_id )
            return local_path
        except Exception as e:
            print( f"Error downloading model: {e}" )
            sys.exit( 1 )

if __name__ == "__main__":

    # sanity check for command line arguments
    if len( sys.argv ) != 2:
        print( "Usage: python hf_downloader.py <repo_id>" )
        sys.exit( 1 )
        
    # sanity check for huggingface home
    if not os.getenv( "HF_HOME" ):
        print( "Please set the HF_HOME environment variable to the directory where you want to download models" )
        sys.exit( 1 )
        
    # Authenticate with Hugging Face
    hf_token = os.getenv( "HF_TOKEN" )
    if not hf_token:
        print( "Please set the HF_TOKEN environment variable with your Hugging Face API token" )
        sys.exit( 1 )
    
    repo_id = sys.argv[ 1 ]
    downloader = HuggingFaceDownloader( token=hf_token )
    downloader.download_model( repo_id )
    
    