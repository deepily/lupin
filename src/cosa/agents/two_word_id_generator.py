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
import threading
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

        # Cycle number for the name space currently being handed out. Cycle 1 is the
        # bare "adjective noun" space; when it fills, cycle 2 opens "adjective noun<a>",
        # and so on. Without this the retry loop below could never find a free name and
        # would spin forever on CPU once all len(adjectives) * len(nouns) were used.
        self._cycle = 1

        # get_id() is called from request-handler and agent-construction threads
        # concurrently. The membership check and the add must be one step, or two
        # threads can hand out the same id.
        self._lock  = threading.RLock()
    
    def _cycle_suffix( self, cycle: int ) -> str:
        """
        Letters appended to the noun to open a fresh name space past the first.

        Letters, not digits, and appended with no separator, so the result is still
        two lowercase words. Session ids from this generator are validated against
        ^[a-z]+ [a-z]+$ in cosa/rest/routers/websocket.py before a WebSocket is
        allowed to connect, and a digit or a third word would be refused.

        Requires:
            - cycle is an integer >= 1

        Ensures:
            - Cycle 1 returns "" (names are unchanged from the original scheme)
            - Cycle 2 returns "a", 3 returns "b", ... 27 returns "z", 28 returns "aa"
            - The returned string is lowercase ASCII letters only

        Raises:
            - None
        """
        suffix = ""
        n      = cycle - 1
        while n > 0:
            n, remainder = divmod( n - 1, 26 )
            suffix       = chr( ord( "a" ) + remainder ) + suffix
        return suffix

    def get_id( self ) -> str:
        """
        Generate a unique two-word identifier.

        Randomly draws an adjective and a noun and returns the pair the first time
        it comes up. The pool holds len( adjectives ) * len( nouns ) names; once a
        cycle is used up the next one opens with letters appended to the noun
        ("bright liona"), so the generator keeps returning unique, readable ids for
        the whole life of the process instead of looping forever.

        Requires:
            - self.adjectives is a non-empty list
            - self.nouns is a non-empty list
            - self.generated_ids is a set

        Ensures:
            - Returns a name that has not been returned before by this instance
            - The returned name is added to generated_ids
            - Always terminates, including when every name in the current cycle is taken
            - The name is always two lowercase words, so it still passes the session-id
              check in cosa/rest/routers/websocket.py (^[a-z]+ [a-z]+$)
            - Safe to call from multiple threads at once

        Raises:
            - None
        """
        with self._lock:
            names_per_cycle = len( self.adjectives ) * len( self.nouns )

            # Open a new cycle whenever the current name space is full. Guarantees the
            # draw loop below always has at least one free name to land on.
            while len( self.generated_ids ) >= names_per_cycle * self._cycle:
                self._cycle += 1

            suffix = self._cycle_suffix( self._cycle )

            while True:
                # Generate a random adjective and noun combination
                adjective   = random.choice( self.adjectives )
                noun        = random.choice( self.nouns )
                combination = f"{adjective} {noun}{suffix}"

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
