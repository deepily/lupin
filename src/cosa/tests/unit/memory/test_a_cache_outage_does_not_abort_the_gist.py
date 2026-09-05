"""
The gist cache is an OPTIMISATION. Losing it must not lose the gist.

THE DEFECT THESE PIN (row 2ab9961b, Rick's P1, 2026-09-04). `Gister.get_gist` reads the
Postgres-backed gist cache BEFORE it calls the LLM, and that read is unguarded. When the
cache backend is unreachable the exception propagates OUT of `get_gist` entirely — the LLM
is never contacted, and every caller's own `except` swallows the raise and substitutes
something plausible.

WHAT THAT LOOKS LIKE IN PRODUCTION, measured rather than reasoned:
`cc_notification_listener._respond_with_gist` catches it, sets `gist = None`, and emits
`" ".join( text.split()[ :5 ] )` — the first five words of the input. That is the "gister
truncates to five words" symptom Rick reported. It reads as a short paraphrase, not as an
outage, which is why the same degradation ran 526 consecutive times over 13 days in July
(2026-07-14 → 07-27) before anyone noticed, and why it took a human eye to catch it again.

⚠️ THE CACHE OUTAGE IS NOT EXOTIC ON THIS BOX. `database.py` reads `DB_PASSWORD`; the
untracked repo-root `.env` supplies `POSTGRES_PASSWORD`; `docker-compose.yml` is the ONLY
thing that translates one into the other, and it does so for CONTAINERS. A host-side
process — every `cc_notification_listener`, every hook, every script — gets neither.
Measured on three live listeners (pids 1393393 / 1057017 / 256591): zero `DB_*` vars and
zero `POSTGRES_PASSWORD`. `get_database_url` defaults the password to `""` rather than
raising, so the failure surfaces as a connection refusal deep inside a cache read instead
of a loud startup error.

WHY THESE ARE THEIR OWN FILE rather than appended to `test_gister.py`: an assertion added
behind an already-failing assertion is carried, not exercised, and a failing SET that
collapses several reasons into one test id cannot tell you which one fired.

Created 2026-09-04 by Maya 🌻 for row 2ab9961b.
"""

import unittest
from unittest.mock import Mock, patch

from cosa.memory.gister import Gister


CACHE_OUTAGE = RuntimeError( "connection to server at \"localhost\" (127.0.0.1), port 5432 "
                             "failed: fe_sendauth: no password supplied" )


class TestACacheOutageDoesNotAbortTheGist( unittest.TestCase ):
    """
    Ensures:
        - a cache READ failure degrades to the LLM instead of aborting the gist
        - a cache WRITE failure still returns the gist the LLM produced
        - a HEALTHY cache still short-circuits on a hit (the fix must not cost the cache)
    """

    def _build_gister( self, cache ):
        """
        Construct a Gister whose whole __init__ dependency chain is mocked, wired to the
        supplied cache double.

        Requires:
            - cache is a Mock standing in for GistCacheTable
        Ensures:
            - returns ( gister, llm_client ); no network, storage or model I/O
        """
        mapping = {
            "gister cache enabled"                : True,
            "gister cache table name"             : "gist_cache",
            "prompt template for gist generation" : "/prompts/gist.txt",
            "llm spec key for gist generation"    : "llm_spec_key",
        }
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None, return_type=None: mapping.get( key, default )

        mock_client  = Mock()
        mock_factory = Mock()
        mock_factory.get_client.return_value = mock_client

        mock_normalizer = Mock()
        mock_normalizer.normalize.side_effect = lambda u: u.lower()

        with patch( "cosa.memory.gister.ConfigurationManager", return_value=mock_config ), \
             patch( "cosa.memory.gister.LlmClientFactory",     return_value=mock_factory ), \
             patch( "cosa.memory.gister.Normalizer",           return_value=mock_normalizer ), \
             patch( "cosa.memory.gister.GistCacheTable",       return_value=cache ), \
             patch( "cosa.memory.gister.du.get_project_root",  return_value="/root" ):
            gister = Gister( debug=False, verbose=False )

        return gister, mock_client

    def _llm_answering( self, answer ):
        """
        Ensures: a context manager under which the LLM leg returns `answer`.
        """
        mock_sr = patch( "cosa.memory.gister.SimpleResponse" )
        return (
            patch( "cosa.memory.gister.du.get_file_as_string", return_value="PROMPT {utterance}" ),
            patch( "cosa.memory.gister.PromptTemplateProcessor" ),
            mock_sr,
            answer,
        )

    def test_a_cache_read_failure_still_returns_the_llm_gist( self ):
        """
        THE DEFECT. A dead cache backend must not take the gist down with it.
        """
        cache = Mock()
        cache.get_cached_gist.side_effect = CACHE_OUTAGE

        gister, client = self._build_gister( cache )
        client.run.return_value = "<response><content>Weather tomorrow in DC</content></response>"

        with patch( "cosa.memory.gister.du.get_file_as_string", return_value="PROMPT {utterance}" ), \
             patch( "cosa.memory.gister.PromptTemplateProcessor" ) as mock_proc, \
             patch( "cosa.memory.gister.SimpleResponse" ) as mock_sr:
            mock_proc.return_value.process_template.side_effect = lambda t, _n: t
            mock_sr.from_xml.return_value.get_content.return_value = "Weather tomorrow in DC"

            gist = gister.get_gist( "what is the weather going to be like tomorrow in DC" )

        self.assertEqual( gist, "Weather tomorrow in DC",
                          "a cache-read outage aborted the gist instead of falling through to the LLM — "
                          "this is the five-word-truncation defect (row 2ab9961b)" )
        client.run.assert_called_once()

    def test_a_cache_write_failure_still_returns_the_llm_gist( self ):
        """
        The gist is already computed by the time the cache is written. Failing to STORE it
        must not discard it.
        """
        cache = Mock()
        cache.get_cached_gist.return_value = None          # a clean MISS
        cache.cache_gist.side_effect       = CACHE_OUTAGE  # the store then fails

        gister, client = self._build_gister( cache )

        with patch( "cosa.memory.gister.du.get_file_as_string", return_value="PROMPT {utterance}" ), \
             patch( "cosa.memory.gister.PromptTemplateProcessor" ) as mock_proc, \
             patch( "cosa.memory.gister.SimpleResponse" ) as mock_sr:
            mock_proc.return_value.process_template.side_effect = lambda t, _n: t
            mock_sr.from_xml.return_value.get_content.return_value = "Weather tomorrow in DC"

            gist = gister.get_gist( "what is the weather going to be like tomorrow in DC" )

        self.assertEqual( gist, "Weather tomorrow in DC",
                          "a cache-WRITE outage discarded a gist the LLM had already produced" )

    def test_a_healthy_cache_still_serves_its_hit( self ):
        """
        POSITIVE CONTROL — proves this file can pass, and that the degradation path does not
        cost the cache its job. Without this, the two tests above would be satisfied by a
        'fix' that simply stopped using the cache at all.
        """
        cache = Mock()
        cache.get_cached_gist.return_value = "Cached answer"

        gister, client = self._build_gister( cache )

        gist = gister.get_gist( "what is the weather going to be like tomorrow in DC" )

        self.assertEqual( gist, "Cached answer" )
        client.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
