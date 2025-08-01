import os
import subprocess
import sys
import tkinter as tk
from threading import Thread
from tkinter import ttk, ACTIVE, DISABLED

import lupin_client as gc
from cosa.utils import util


class CmdUi:

    def __init__( self, recording_timeout=15, copy_transx_to_clipboard=False, debug=False ):
        """
        Initialize the command-line UI with Tkinter interface and GenieClient integration.
        
        Requires:
            - Tkinter must be available
            - GenieClient (lupin_client) must be available
            - CLI commands configuration file must exist (conf/cli-commands.map)
            - util module must be available
            
        Ensures:
            - Creates main Tkinter window with console and command interface
            - Initializes GenieClient with specified configuration
            - Sets up GUI components (text console, command entry, buttons)
            - Loads command dictionary from configuration file
            - GUI enters mainloop for user interaction
            
        Args:
            recording_timeout: Maximum recording duration in seconds (default: 15)
            copy_transx_to_clipboard: Auto-copy transcriptions to clipboard (default: False)
            debug: Enable debug logging (default: False)
            
        Returns:
            None
            
        Raises:
            ImportError: If required modules are not available
            FileNotFoundError: If CLI commands configuration file is missing
            Exception: If GUI initialization fails
        """

        self.debug = debug
        self.cwd = os.getcwd()
        print( "Current working directory [{}]".format( self.cwd ) )

        self.cmd_dict = util.get_file_as_dictionary( self.cwd + "/conf/cli-commands.map", debug=debug )

        self.root = tk.Tk()  # create root window
        self.root.title( "Frame Example" )
        self.root.config( bg="skyblue" )
        self.root.geometry( "600x400" )
        self.root.eval( 'tk::PlaceWindow . center' )

        self.top_frame = tk.Frame( self.root, bg="red" )
        self.top_frame.grid( row=0, column=0, padx=10, pady=5 )

        self.txt_console = tk.Text( self.top_frame )
        self.txt_console.grid( row=0, column=0, sticky=tk.NSEW )

        self.bottom_frame = tk.Frame( self.root, bg="green" )
        self.bottom_frame.grid( row=1, column=0, padx=10, pady=5 )

        self.selected_path = tk.StringVar()
        self.cmb_path = ttk.Combobox( self.bottom_frame, state="readonly", textvariable=self.selected_path )
        self.cmb_path[ "values" ] = [ "/lupin", "/lupin-plugin-firefox", "/lupin-plugin-intellij" ]
        self.cmb_path.current( 0 )
        self.cmb_path.bind( "<<ComboboxSelected>>", lambda event: self.update_path() )
        self.cmb_path.grid( row=0, column=0, padx=5, pady=5, sticky=tk.EW )

        self.txt_cmd = tk.Entry( self.bottom_frame )
        self.txt_cmd.grid( row=1, column=0, columnspan=18, sticky=tk.EW )
        self.txt_cmd.insert( tk.END, "Enter a command" )
        self.txt_cmd.bind( "<Return>", lambda event: self.execute_command() )

        # Start and Stop buttons
        self.btn_start = tk.Button(
            self.bottom_frame, padx=0, pady=5, text="G", command=lambda: self.start_processing()
        )
        self.btn_start.grid( row=1, column=18, padx=0, pady=5 )

        self.btn_stop = tk.Button(
            self.bottom_frame, padx=0, pady=5, text="S", command=lambda: self.stop_processing()
        )
        self.btn_stop.config( state=DISABLED )
        self.btn_stop.grid( row=1, column=19, padx=0, pady=5 )

        self.update_path()

        self.btn_start.focus_set()

        self.lupin_lupin = gc.GenieClient( calling_gui=self.root, copy_transx_to_clipboard=copy_transx_to_clipboard,
                                            debug=debug, recording_timeout=recording_timeout
                                            )

        self.root.mainloop()

    def execute_command( self ):
        """
        Execute the command entered in the command text field.
        
        Requires:
            - txt_cmd widget must be initialized and contain valid text
            - Command must be a valid system command or empty string
            
        Ensures:
            - Executes command using subprocess.Popen
            - Displays command output in console text widget
            - Shows live stdout output during execution
            - Handles command completion and error codes
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            subprocess.CalledProcessError: If command exits with non-zero return code
            Exception: If subprocess execution fails
        """

        command = self.txt_cmd.get().strip()
        print( "Execute command [{}]...".format( command ) )
        if command == "":
            print( "No command to execute" )
            return

        command = command.split( " " )
        print( "Command [{}]".format( command ) )
        self.txt_console.insert( tk.END, "Executing command {}... ".format( command ) )
        process = subprocess.Popen( command, shell=False, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1, universal_newlines=True )
        self.txt_console.insert( tk.END, "Done!\n\n" )

        # Poll process.stdout to show stdout live
        while True:
            output = process.stdout.readline()
            if process.poll() is not None:
                break
            if output:
                self.txt_console.insert( tk.END, output.strip() + "\n" )
                print( output.strip() )

        rc = process.poll()

        if self.debug: print( "rc: {}".format( rc ) )
        if rc != 0:
            raise subprocess.CalledProcessError( process.returncode, process.args )

    def update_path( self ):

        self.txt_console.insert( tk.END, "Current path: {}{}\n".format( self.cwd, self.selected_path.get() ) )

    def start_processing( self ):
        """
        Start audio recording and transcription processing.
        
        Requires:
            - GUI components must be initialized (btn_start, btn_stop, txt_console)
            - lupin_lupin client must be initialized
            
        Ensures:
            - Disables start button and enables stop button
            - Updates console with recording status
            - Starts processing thread for audio transcription
            - Shifts focus to stop button
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            AttributeError: If GUI components are not initialized
            Exception: If processing thread fails to start
        """

        print( "Start processing..." )
        self.btn_start.config( state=DISABLED )
        self.btn_stop.config( state=ACTIVE )

        self.txt_console.insert( tk.END, "Recording... " )
        self.btn_stop.focus_set()

        processing_thread = Thread( target=self._start_processing_thread(), args=() )
        processing_thread.start()

    def stop_processing( self ):
        """
        Stop audio recording and transcription processing.
        
        Requires:
            - GUI components must be initialized (btn_start, btn_stop, txt_console)
            - lupin_lupin client must be initialized
            
        Ensures:
            - Re-enables start button and disables stop button
            - Updates console with completion status
            - Stops recording in lupin_lupin client
            - Shifts focus to start button
            
        Args:
            None
            
        Returns:
            None
            
        Raises:
            AttributeError: If GUI components are not initialized
        """

        print( "Stop processing..." )
        self.btn_start.config( state=ACTIVE )
        self.btn_stop.config( state=DISABLED )

        self.txt_console.insert( tk.END, "Done!\n" )
        self.btn_start.focus_set()

        self.lupin_lupin.stop_recording()

    def _start_processing_thread( self ):

        if self.debug: print( "Processing. on a separate thread...", end="" )
        transcription = self.lupin_lupin.do_transcribe_and_clean_python()

        self.txt_console.insert( tk.END, "Transcription [{}]\n".format( transcription ) )

        command = self.cmd_dict.get( transcription, None )

        if command is None:
            print( "Command not found in cmd_dict: [{}]".format( transcription ) )
        else:
            self.txt_cmd.delete( 0, tk.END )
            # self.txt_cmd.insert( tk.END, self.cwd + "/" + command )
            self.txt_cmd.insert( tk.END, command )
            self.txt_cmd.focus_set()

# add main method
if __name__ == "__main__":

    debug = True
    cli_args = util.get_name_value_pairs( sys.argv )

    startup_mode = cli_args.get( "startup_mode", "transcribe_and_clean_python" )
    record_once_on_startup = cli_args.get( "record_once_on_startup", "FALSE" ) == "True"
    copy_transx_to_clipboard = cli_args.get( "copy_transx_to_clipboard", "True" ) == "True"
    recording_timeout = int( cli_args.get( "recording_timeout", 15 ) )

    if debug:
        print( "     startup_mode: [{}]".format( startup_mode ) )
        print( "recording_timeout: [{}]".format( recording_timeout ) )

    ui = CmdUi( recording_timeout=recording_timeout, copy_transx_to_clipboard=copy_transx_to_clipboard, debug=debug )