import argparse

import os
import time

import pandas             as pd

import cosa.utils.util as du
import cosa.utils.util_xml as dux

# from lib.memory.solution_snapshot    import SolutionSnapshot
from cosa.utils.util_stopwatch import Stopwatch
from cosa.agents.math_agent import MathAgent
from cosa.agents import Llm


def get_questions( path ):
    
    df = pd.read_parquet( path, engine="pyarrow" )
    
    df.rename( columns={ "answer": "answer_long" }, inplace=True )
    # extract the answer from the long answer and strip out any characters that are not digits
    df[ "answer" ] = df[ "answer_long" ].str.split( "####" ).str[ 1 ].str.strip().replace( r"[^0-9]", "", regex=True )
    cols = [ "question", "answer" ]
    
    return df[ cols ]

def call_vanilla_llm( prefix, prompt, model=Llm.PHI_4_14B, debug=False, verbose=False ):
    answer = "Unable to answer"
    try:
        llm = Llm( model=model, debug=debug, verbose=verbose )
        results = llm.query_llm( prompt=prompt )
        answer = dux.get_value_by_xml_tag_name( results, "answer" ).strip()
    
    except Exception as e:
        
        if debug: du.print_stack_trace( e, explanation=model, caller=prefix, prepend_nl=True )
    
    return answer


def call_llms(
    max_rows, questions, ground_truth, model=Llm.PHI_4_14B, starting_i=0, checkpoint_interval=10, sleep_seconds=0, checkpoint_path="/var/model/benchmarks/gsm8k/checkpoints",
    do_math_agent=True, do_vanilla_llm=False, do_vanilla_llm_cot=False, debug=False, verbose=False
):
    
    responses_math_agent      = [ ]
    responses_vanilla_llm     = [ ]
    responses_vanilla_llm_toc = [ ]
    
    total_rows_processed      = 0
    last_checkpoint           = -1
    i = starting_i
    
    outer_timer  = Stopwatch( f"Answering {len( questions )} questions..." )
    current_date = du.get_current_date()
    current_time = du.get_current_time( include_timezone=False )
    
    for question in questions[ i:max_rows ]:
        
        try:
            # test for checkpoint writing
            if i % checkpoint_interval == 0 and i >= checkpoint_interval and total_rows_processed >= checkpoint_interval:
                
                last_checkpoint = i - 1
                file_name = get_file_name( model, current_date, current_time )
                checkpoint_file = f"{checkpoint_path}/checkpoint-{starting_i}-{i - 1}-{file_name}"
                du.print_banner( f"Writing INNER checkpoint @ [{i - 1}]: {checkpoint_file}" )
                df = pd.DataFrame( {
                    "question"                 : questions[ starting_i:i ],
                    "ground_truth"             : ground_truth[ starting_i:i ],
                    "responses_math_agent"     : responses_math_agent,
                    "responses_vanilla_llm"    : responses_vanilla_llm,
                    "responses_vanilla_llm_toc": responses_vanilla_llm_toc
                } )
                df.to_csv( checkpoint_file, index=True )
        
            du.print_banner( f"Question [{i}] of [{max_rows}]: {question[ :100 ]}" )
            if do_math_agent:
                
                # timer = Stopwatch()
                agent = MathAgent(
                    # question=SolutionSnapshot.remove_non_alphanumerics( question ),
                    question=question,
                    last_question_asked=question,
                    routing_command="agent router go to math", debug=debug, verbose=verbose
                )
                answer = agent.do_all()
                responses_math_agent.append( answer )
                # timer.print( f"Math agent answered: {answer}", use_millis=True )
            else:
                responses_math_agent.append( "" )
            
            if do_vanilla_llm:
                
                prefix = "Plain vanilla LLM"
                # timer = Stopwatch( f"[{i}] {prefix}..." )
                prompt_template = du.get_file_as_string(
                    du.get_project_root() + "/src/conf/prompts/agents/plain-vanilla-question.txt"
                    )
                prompt = prompt_template.format( question=question )
                answer = call_vanilla_llm( prefix, prompt, model=model, debug=debug, verbose=verbose )
                responses_vanilla_llm.append( answer )
                # timer.print( "Done!", use_millis=True )
            else:
                responses_vanilla_llm.append( "" )
            
            if do_vanilla_llm_cot:
                
                prefix = "Plain vanilla LLM w/ ToC"
                # timer = Stopwatch( f"[{i}] {prefix}..." )
                prompt_template = du.get_file_as_string(
                    du.get_project_root() + "/src/conf/prompts/agents/plain-vanilla-question-toc.txt"
                )
                prompt = prompt_template.format( question=question )
                answer = call_vanilla_llm( prefix, prompt, model=model, debug=debug, verbose=verbose )
                responses_vanilla_llm_toc.append( answer )
                # timer.print( "Done!", use_millis=True )
            
            else:
                responses_vanilla_llm_toc.append( "" )
            
            # # if we're only running vanilla, wait a bit before continuing so as to not overwhelm the server
            # if do_vanilla and not do_vanilla_cot and not do_math_agent:
            #     print( f"We're only running in vanilla mode, waiting [{seconds}]... before continuing" )
            #     time.sleep( seconds )
            
            if sleep_seconds > 0:
                print( f"Sleeping for [{sleep_seconds}] seconds..." )
                time.sleep( sleep_seconds )
            else:
                print( "No sleep requested, continuing..." )
                
            i += 1
            total_rows_processed += 1
            
            
        except Exception as e:
            
            du.print_stack_trace( e, explanation="LLM Error in GSM8K", caller="GSM8K.call_llms(...)", prepend_nl=True )
            if last_checkpoint != -1:
                du.print_banner( f"Last checkpoint run for row [{[last_checkpoint]}], you can reenter loop using [{last_checkpoint + 1}] for `starting_i`" )
            else:
                du.print_banner( f"First checkpoint not yet reached, you're going to have to start over again @ starting_i [{starting_i}] " )
                
            # raising the error here causes to skip the rest of the processing below
            raise e
                
    outer_timer.print( "Done!" )
    
    # write final checkpoint AFTER decrementing the counter by one    
    # i -= 1
    
    file_name = get_file_name( model, current_date, current_time )
    checkpoint_file = f"{checkpoint_path}/checkpoint-{starting_i}-{i - 1}-{file_name}"
    du.print_banner( f"Writing OUTER checkpoint: {checkpoint_file}" )
    df = pd.DataFrame( {
        "question"                 : questions[ starting_i:i ],
        "ground_truth"             : ground_truth[ starting_i:i ],
        "responses_math_agent"     : responses_math_agent[ 0:i ],
        "responses_vanilla_llm"    : responses_vanilla_llm[ 0:i ],
        "responses_vanilla_llm_toc": responses_vanilla_llm_toc[ 0:i ]
    })
    df.to_csv( checkpoint_file, index=True )
    
    # iterate and append zero len string for remaining questions
    for i in range( max_rows, len( questions ) ):
        responses_math_agent.append( "" )
        responses_vanilla_llm.append( "" )
        responses_vanilla_llm_toc.append( "" )
    
    responses_dict = {
        "responses_math_agent"     : responses_math_agent,
        "responses_vanilla_llm"    : responses_vanilla_llm,
        "responses_vanilla_llm_toc": responses_vanilla_llm_toc
    }
    return responses_dict

def can_be_float( value: str ) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False
    
def can_be_int(value: str) -> bool:
    try:
        int( value )
        return True
    except ValueError:
        return False
    
def compile_stats( max_rows, prefix, questions, responses, ground_truth ):
    
    du.print_banner( f"Compiling stats for {prefix}...", prepend_nl=True )
    grades     = [ ]
    comparison = [ ]
    
    for i in range( max_rows ):
        
        print( f"Question [{i}] of [{max_rows}]: [{questions[ i ][ :100 ]}]..." )
        print( f"Ground truth: [{ground_truth[ i ]}]" )
        print( f"{prefix}: [{responses[ i ][ -100: ]}]" )
        correct = False
        method  = None
        
        if ground_truth[ i ] == responses[ i ]:
            correct = True
            method  = "string equals"
        elif can_be_int( ground_truth[ i ] ) and can_be_int( responses[ i ] ):
            correct = int( ground_truth[ i ] ) == int( responses[ i ] )
            method  = "int"
        elif can_be_float( ground_truth[ i ] ) and can_be_float( responses[ i ] ):
            correct = float( ground_truth[ i ] ) == float( responses[ i ] )
            method  = "float"
        elif ground_truth[ i ] in responses[ i ][ -100: ].replace( ",", "" ).replace( "$", "" ):
            correct = True
            method  = "string in"
        
        print( f"Correct: {correct}" )
        print( f"Method: {method}" )
        comparison.append( method )
        grades.append( correct )
        print()
    
    correct = sum( grades )
    mean = correct / (max_rows * 1.0) * 100
    du.print_banner( f"Compiling stats for {prefix}... Done! Correct: {correct}/{max_rows} = {mean:.1f}%" )
    
    # iterate through the remainder of the rose and assign None
    for i in range( max_rows, len( ground_truth ) ):
        grades.append( None )
    
    responses_dict = {
        "grades"     : grades,
        "comparison" : comparison
    }
    return responses_dict

def get_file_name( model, current_date=du.get_current_date(), current_time=du.get_current_time( include_timezone=False ) ):
    
    file_name = f"results-{current_date}-at-{current_time}-{model.lower()}.csv"
    file_name = file_name.replace( ":", "-" ).replace( "/", "-" )
    
    return file_name

def get_cli_args():
    
    # Create the parser
    parser = argparse.ArgumentParser( description="CLI arguments" )
    
    # Add arguments
    parser.add_argument( '--debug', action='store_true', default=False, help='Enable debug mode (default: False)' )
    parser.add_argument( '--verbose', action='store_true', default=False, help='Enable verbose mode (default: False)' )
    parser.add_argument( "--starting-i", type=int, default=0, help="Which row of the gsm8k question should we start with? (default: 0)" )
    parser.add_argument( "--checkpoint", type=int, default=10, help="How often will we write a checkpoint? (default: 10)" )
    parser.add_argument( "--sleep-seconds", type=int, default=0, help="How long should we wait before continuing w/ the next iteration? (default: 0)" )
    parser.add_argument( '--do-vanilla', action='store_true', default=False, help='Run vanilla prompt (default: False)' )
    parser.add_argument( '--do-vanilla-cot', action='store_true', default=False, help='Run vanilla prompt w/ CoT (default: False)' )
    parser.add_argument( '--do-math-agent', action='store_true', default=False, help='Run math agent w/ CoT (default: False)' )
    
    # Parse the arguments
    args = parser.parse_args()
    
    return args

if __name__ == "__main__":
    
    # this is designed to be run from within a container that has access to all of the projects mounted on /var/model
    # test to see if an environmental variable has been set
    du.print_banner( "Checking environment variables..." )
    if "GENIE_IN_THE_BOX_ROOT" not in os.environ:
        default = "/var/model/genie-in-the-box"
        print( f"GENIE_IN_THE_BOX_ROOT not set, using default [{default}]..." )
        os.environ[ "GENIE_IN_THE_BOX_ROOT"       ] = default
    else:
        env_value = os.environ[ "GENIE_IN_THE_BOX_ROOT" ]
        print( f"Using env.GENIE_IN_THE_BOX_ROOT [{env_value}]" )
        
    if "GENIE_IN_THE_BOX_TGI_SERVER" not in os.environ:
        default = "http://127.0.0.1:3000/v1"
        print( f"GENIE_IN_THE_BOX_TGI_SERVER not set, using default [{default}]..." )
        os.environ[ "GENIE_IN_THE_BOX_TGI_SERVER" ] = default
    else:
        env_value = os.environ[ "GENIE_IN_THE_BOX_TGI_SERVER" ]
        print( f"Using env.GENIE_IN_THE_BOX_TGI_SERVER [{env_value}]" )
        
    if "GIB_CONFIG_MGR_CLI_ARGS" not in os.environ:
        default = "config_path=/src/conf/gib-app.ini splainer_path=/src/conf/gib-app-splainer.ini config_block_id=Genie+in+the+Box:+Development"
        print( f"GIB_CONFIG_MGR_CLI_ARGS not set, using default [{default}]..." )
        os.environ[ "GIB_CONFIG_MGR_CLI_ARGS"     ] = default
    else:
        env_value = os.environ[ "GIB_CONFIG_MGR_CLI_ARGS" ]
        print( f"Using env.GIB_CONFIG_MGR_CLI_ARGS [{env_value}]" )
    
    args = get_cli_args()
    
    starting_i     = args.starting_i
    do_vanilla     = args.do_vanilla
    do_vanilla_cot = args.do_vanilla_cot
    do_math_agent  = args.do_math_agent
    debug          = args.debug
    verbose        = args.verbose
    checkpoint_i   = args.checkpoint
    sleep_seconds  = args.sleep_seconds
    
    if not do_vanilla and not do_vanilla_cot and not do_math_agent:
        du.print_banner( "No agents selected, exiting...", prepend_nl=True )
        exit( 0 )
    
    du.print_banner( f"Starting GSM8K with:", prepend_nl=True )
    print( f"starting_i: {starting_i}" )
    print()
    
    df = get_questions( "/var/model/benchmarks/gsm8k/test-00000-of-00001.parquet" )
    sampled_df = df.sample( frac=0.1, random_state=42 ).copy()
    
    questions       = sampled_df[ "question" ].tolist()
    ground_truth    = sampled_df[ "answer" ].tolist()
    max_rows        = len( questions )
    model           = Llm.PHI_4_14B
    # model           = Llm.QWEN_2_5_32B
    # model           = Llm.PHIND_34B_v2
    # model           = Llm.GROQ_LLAMA3_1_8B
    # model           = Llm.GROQ_LLAMA3_1_70B
    
    llm_responses_dict = call_llms(
        max_rows, questions, ground_truth, model=model, starting_i=starting_i, checkpoint_interval=checkpoint_i, sleep_seconds=sleep_seconds,
        do_math_agent=do_math_agent, do_vanilla_llm=do_vanilla, do_vanilla_llm_cot=do_vanilla_cot, debug=debug, verbose=verbose
    )
    # for now, only run stats if we have the entire data set
    if starting_i == 0 and len( llm_responses_dict[ "responses_vanilla_llm" ] ) == len( questions ):
        
        stats_dict                 = compile_stats( max_rows,"Vanilla LLM", questions, llm_responses_dict[ "responses_vanilla_llm" ], ground_truth )
        grades_vanilla_llm         = stats_dict[ "grades" ]
        comparison_vanilla_llm     = stats_dict[ "comparison" ]
        
        stats_dict                 = compile_stats( max_rows,"Vanilla LLM w/ ToC", questions, llm_responses_dict[ "responses_vanilla_llm_toc" ], ground_truth )
        grades_vanilla_llm_toc     = stats_dict[ "grades" ]
        comparison_vanilla_llm_toc = stats_dict[ "comparison" ]
        
        stats_dict                 = compile_stats( max_rows,"Math agent", questions, llm_responses_dict[ "responses_math_agent" ], ground_truth )
        grades_math_agent          = stats_dict[ "grades" ]
        comparison_math_agent      = stats_dict[ "comparison" ]
        
        sampled_df[ "resp_math_agent" ]            = llm_responses_dict[ "responses_math_agent" ]
        sampled_df[ "resp_vanilla_llm" ]           = llm_responses_dict[ "responses_vanilla_llm" ]
        sampled_df[ "resp_vanilla_llm_toc" ]       = llm_responses_dict[ "responses_vanilla_llm_toc" ]
        
        sampled_df[ "grades_math_agent" ]          = grades_math_agent
        sampled_df[ "grades_vanilla_llm" ]         = grades_vanilla_llm
        sampled_df[ "grades_vanilla_llm_toc" ]     = grades_vanilla_llm_toc
        
        sampled_df[ "comparison_math_agent" ]      = comparison_math_agent
        sampled_df[ "comparison_vanilla_llm" ]     = comparison_vanilla_llm
        sampled_df[ "comparison_vanilla_llm_toc" ] = comparison_vanilla_llm_toc
        
        file_name = get_file_name( model )
        file_path = f"/var/model/benchmarks/gsm8k/{file_name}"
        print( f"Writing final results to [{file_path}]..." )
        sampled_df.to_csv( file_path, index=False )
        print( f"Writing final results to [{file_path}]... Done!" )
        
    else:
        du.print_banner( f"Partial run, skipping stats..." )
    
    
    