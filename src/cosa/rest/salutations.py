"""Salutation stripping, shared by the v1 queue and the v2 flow.

This lived as a method + a hardcoded list on `TodoFifoQueue`. The v2 flow needs
the same answer to build the agent the queue builds (step 4, agent-construction
parity): `question_gist` is computed from the SALUTATION-STRIPPED question, and
`last_question_asked` carries the salutation. Two copies of a word list is how
two surfaces start disagreeing about what a greeting is, so there is one.
"""

from __future__ import annotations


# Stripped by brute force until the router parses them off for us. Moved here
# verbatim from TodoFifoQueue.__init__ — do not "tidy" it; every entry is a word
# some user actually opens with.
SALUTATIONS = [
    "computer", "little", "buddy", "pal", "ai", "jarvis", "alexa", "siri", "hal", "einstein",
    "jeeves", "alfred", "watson", "samwise", "sam", "hawkeye", "oye", "hey", "there", "you", "yo",
    "hi", "hello", "hola", "good", "morning", "afternoon", "evening", "night", "buenas", "buenos", "buen", "tardes",
    "noches", "dias", "día", "tarde", "greetings", "my", "dear", "dearest", "esteemed", "assistant", "receptionist", "friend",
]


def parse_salutations( transcription: str, salutations=None ) -> tuple[ str, str ]:
    """
    Split leading salutations off a transcription.

    Requires:
        - transcription is a string.

    Ensures:
        - returns ( salutations, remaining_text ), both possibly empty strings.
        - only a LEADING run is taken: the first word that is not a salutation
          ends the run, so "hey there is my package here" keeps "is my package
          here" intact.
        - trailing punctuation is ignored when matching, and the original words
          (punctuation included) are what come back in the salutation half.
    """
    words         = transcription.split()
    known         = salutations if salutations is not None else SALUTATIONS
    prefix_holder = []

    index = 0
    for word in words:
        if word.strip( ',.:;!?' ).lower() in known:
            prefix_holder.append( word )
            index += 1
        else:
            break

    return ' '.join( prefix_holder ), ' '.join( words[ index: ] )
