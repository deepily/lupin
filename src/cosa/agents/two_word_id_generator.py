"""
two_word_id_generator.py

A Python module that provides functionality for generating unique, memorable two-word IDs.
The IDs consist of a combination of an adjective and a noun, ensuring that each combination is unique by tracking previously generated IDs.
This module employs the Singleton design pattern to ensure that only one instance of the ID generator exists throughout the runtime.

Classes:
    TwoWordIDGenerator: A class responsible for generating unique two-word combinations and ensuring no duplicates.

Decorators:
    singleton: A decorator that enforces the Singleton design pattern on a class, ensuring only one instance is created.

Usage Example:
    generator = TwoWordIdGenerator()
    unique_id = generator.get_id()
    print(unique_id)
    'bright lion'

    # Ensure the Singleton pattern:
    another_generator = TwoWordIdGenerator()
    print(generator is another_generator)
    True

Attributes:
    adjectives (list): A list of adjectives to be used for generating combinations.
    nouns (list): A list of nouns to be used for generating combinations.
    generated_ids (set): A set storing all previously generated unique IDs to prevent duplicates.

Methods:
    generate_unique_id(): Generates a unique two-word ID by combining an adjective and a noun.

"""

import random
from functools import wraps
from typing import Callable, Any

import cosa.utils.util as du

# Singleton decorator
def singleton( cls: type ) -> Callable[..., Any]:
    """
    Decorator that implements the Singleton pattern.
    
    Requires:
        - cls is a valid class type
        
    Ensures:
        - Only one instance of cls is created
        - All calls return the same instance
        - Thread-safe in single-threaded environments
        
    Raises:
        - None
    """
    instances = { }
    
    @wraps( cls )
    def get_instance( *args: Any, **kwargs: Any ) -> Any:
        if cls not in instances:
            instances[ cls ] = cls( *args, **kwargs )
        return instances[ cls ]
    
    return get_instance

# The TwoWordIDGenerator class with a singleton decorator
@singleton
class TwoWordIdGenerator:
    """
    Generator for unique two-word identifiers.
    
    Uses the Singleton pattern to ensure consistent ID generation
    across the application. Combines adjectives and nouns to create
    memorable, unique identifiers.
    """
    
    def __init__( self ) -> None:
        """
        Initialize the generator with word lists.
        
        Requires:
            - No external dependencies
            
        Ensures:
            - Initializes adjectives and nouns lists
            - Creates empty set for tracking generated IDs
            - Single instance via singleton decorator
            
        Raises:
            - None
        """
        # List of adjectives and nouns
        self.adjectives = [
            'beautiful', 'quick', 'shiny', 'clever', 'silent', 'brave', 'lazy', 'strong',
            'fierce', 'gentle', 'happy', 'sad', 'wild', 'calm', 'bright', 'dark',
            'wise', 'foolish', 'fast', 'slow', 'bold', 'timid', 'eager', 'relaxed',
            'loyal', 'faithful', 'mighty', 'tiny', 'graceful', 'clumsy', 'proud', 'humble'
        ]
        self.nouns = [
            'giraffe', 'lion', 'falcon', 'tiger', 'elephant', 'panda', 'dolphin', 'rhino',
            'zebra', 'koala', 'owl', 'wolf', 'fox', 'bear', 'whale', 'eagle',
            'shark', 'penguin', 'cheetah', 'kangaroo', 'octopus', 'rabbit', 'squirrel', 'otter',
            'turtle', 'hawk', 'chimp', 'moose', 'bison', 'leopard', 'goat', 'sheep'
        ]
        
        # Dictionary to store generated unique combinations
        self.generated_ids = set()  # Using a set for faster lookup
    
    def get_id( self ) -> str:
        """
        Generate a unique two-word identifier.
        
        This method randomly selects an adjective and a noun from the
        pre-defined lists and combines them to form a unique identifier.
        The generated identifier is stored in the `generated_ids` set
        to ensure that it is not generated again.
        
        Requires:
            - self.adjectives is non-empty list
            - self.nouns is non-empty list
            - self.generated_ids is a set
            
        Ensures:
            - Returns unique adjective-noun combination
            - Combination is added to generated_ids set
            - Never returns duplicate IDs
            - Eventually exhausts all combinations
            
        Raises:
            - None (infinite loop if all combinations used)
        """
        while True:
            # Generate a random adjective and noun combination
            adjective = random.choice( self.adjectives )
            noun = random.choice( self.nouns )
            combination = f"{adjective} {noun}"
            
            # Check if this combination has already been generated in this session
            if combination not in self.generated_ids:
                # If unique, store it in the dictionary and return it
                self.generated_ids.add( combination )
                return combination

def quick_smoke_test():
    """Quick smoke test to validate TwoWordIdGenerator functionality."""
    du.print_banner( "TwoWordIdGenerator Smoke Test", prepend_nl=True )
    
    # Example usage
    generator = TwoWordIdGenerator()
    unique_id = generator.get_id()
    print( f"Generated unique ID: {unique_id}" )
    
    # Creating another "instance" will return the same generator
    another_generator = TwoWordIdGenerator()
    print( f"Same instance? {generator is another_generator}" )
    
    # Generate a few more to show uniqueness
    print( f"Second ID: {generator.get_id()}" )
    print( f"Third ID: {generator.get_id()}" )


if __name__ == "__main__":
    quick_smoke_test()
