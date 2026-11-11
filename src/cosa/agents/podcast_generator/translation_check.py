"""
Tells a real Spanish translation from English text returned unchanged.

The translation step sometimes hands back the English text. That text then ships as a normally
titled es-MX script. A Spanish script is full of function words such as de, la, que and el.
Those words are rare in English, so their share of all words separates the two.
"""

import re

# Spanish function words. The list is closed: it is the check's whole vocabulary.
SPANISH_STOPWORDS = frozenset( (
    "de la que el en y a los se del las un por con no una su para es al lo como más pero sus le ya o "
    "este sí porque esta entre cuando muy sin sobre también me hasta hay donde quien desde todo nos "
    "durante todos uno les ni contra otros ese eso ante ellos e esto antes algunos qué unos yo otro "
    "otras otra él tanto esa estos mucho quienes nada muchos cual poco ella estar estas algunas algo "
    "nosotros mi mis tú te ti tu tus ellas nosotras os"
).split() )

_WORD = re.compile( r"[a-záéíóúñü]+" )


def spanish_stopword_ratio( text ):
    """
    Share of the words in text that are Spanish function words.

    Requires:
        - text is a string

    Ensures:
        - returns a float from 0.0 to 1.0
        - returns 0.0 when text holds no words
    """
    words = _WORD.findall( text.lower() )
    if not words: return 0.0
    return sum( 1 for word in words if word in SPANISH_STOPWORDS ) / len( words )
