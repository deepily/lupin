"""
Refuse a run whose model server is not answering — row b9604f8c.

WHY THIS EXISTS. On 2026-08-17 the Ministral-8B router at 192.168.1.21:3000 went down.
Port 3001 (Phi-4) stayed up, so the box looked alive to any casual check, and the outage
surfaced only when a THREE-HOUR JOB DIED ON IT — with an API error three layers from the
cause. The outage was fixed the same day. The DETECTION is what this module is about: a
dead dependency read as a working one, because only one of two ports was ever checked.

TWO THINGS IT MUST DO, both taken from the incident:

  · PROBE EVERY PORT THE RUN WILL USE, not one of them. Half-alive read as alive is what
    made the outage invisible; a probe that checks one port reproduces the defect it was
    built to prevent.
  · NAME WHICH PORT DID NOT ANSWER, and how it failed. "The model server is down" at hour
    three teaches nobody anything; "3000 refused the connection, 3001 answered with
    Phi-4" at second one is self-diagnosing.

WHAT IT DELIBERATELY DOES NOT DO. It does not judge whether the right MODEL is loaded, and
it does not measure latency. It answers one question — did this endpoint answer — because a
probe that can fail for many reasons is a probe whose refusal has to be diagnosed itself.
"""

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional


VLLM_SCHEME       = "vllm://"
MODELS_PATH       = "/v1/models"
DEFAULT_TIMEOUT_S = 5.0


class ModelServerUnavailable( RuntimeError ):
    """Raised to REFUSE a run before it spends hours against a dependency that is not there."""


def parse_vllm_endpoint( spec: Any ) -> Optional[ str ]:
    """
    Pull `host:port` out of a `vllm://host:port@model` config value.

    Ensures:
        - returns None for anything that is not a vllm:// spec, including non-strings,
          so a whole config block can be swept without pre-filtering
        - returns the host:port exactly as configured — the endpoint the run will dial
    """
    if not isinstance( spec, str ) or not spec.startswith( VLLM_SCHEME ):
        return None
    host_port = spec[ len( VLLM_SCHEME ): ].split( "@", 1 )[ 0 ].strip()
    return host_port or None


def discover_vllm_endpoints( config_mgr ) -> List[ str ]:
    """
    The distinct set of vLLM endpoints this configuration points at.

    Ensures:
        - returns each host:port ONCE, sorted, so a run probes every port it could dial
          without probing the same one thirty times
        - is derived from the config the run itself reads, so a new endpoint added to
          lupin-app.ini is probed without anyone remembering to update a list here
    """
    found = set()
    for key in config_mgr.get_keys():
        endpoint = parse_vllm_endpoint( config_mgr.get( key, default=None, silent=True ) )
        if endpoint is not None:
            found.add( endpoint )
    return sorted( found )


def probe_endpoint( endpoint: str, timeout_s: float = DEFAULT_TIMEOUT_S,
                    url_opener: Optional[ Callable ] = None ) -> Dict[ str, Any ]:
    """
    Ask one endpoint whether it is serving, and describe the answer.

    Requires:
        - endpoint is "host:port"

    Ensures:
        - returns {endpoint, alive, detail, models} and NEVER raises: a probe that can
          throw turns a diagnosis into a second failure to diagnose
        - `detail` names the failure in the words an operator can act on — refused,
          timed out, HTTP status, unreadable body — never a bare False
        - `models` carries what the server said it is serving when it answered, so the
          receipt is "3001 answered with Phi-4", not "3001 answered"
    """
    url    = f"http://{endpoint}{MODELS_PATH}"
    opener = url_opener if url_opener is not None else urllib.request.urlopen
    try:
        with opener( url, timeout=timeout_s ) as response:
            status = response.status
            body   = response.read().decode( "utf-8", errors="replace" )
    except urllib.error.HTTPError as e:
        return { "endpoint": endpoint, "alive": False,
                 "detail": f"answered HTTP {e.code} at {url}", "models": [] }
    except ( urllib.error.URLError, socket.timeout, OSError ) as e:
        reason = getattr( e, "reason", e )
        return { "endpoint": endpoint, "alive": False,
                 "detail": f"did not answer at {url} ({reason})", "models": [] }

    if status != 200:
        return { "endpoint": endpoint, "alive": False,
                 "detail": f"answered HTTP {status} at {url}", "models": [] }
    try:
        models = [ entry.get( "id" ) for entry in json.loads( body ).get( "data", [] ) ]
    except ( ValueError, AttributeError ):
        # It answered, but not with a model list. That is a live socket in front of
        # something that is not vLLM — worth naming rather than passing as healthy.
        return { "endpoint": endpoint, "alive": False,
                 "detail": f"answered at {url} but not with a model list", "models": [] }
    return { "endpoint": endpoint, "alive": True,
             "detail": f"serving {models}", "models": models }


def probe_endpoints( endpoints: List[ str ], timeout_s: float = DEFAULT_TIMEOUT_S,
                     url_opener: Optional[ Callable ] = None ) -> List[ Dict[ str, Any ] ]:
    """
    Probe every endpoint and report on each.

    Ensures:
        - EVERY endpoint is probed even after one fails — stopping at the first dead port
          would hide a second dead one, which is the half-alive reading all over again
    """
    return [ probe_endpoint( e, timeout_s=timeout_s, url_opener=url_opener ) for e in endpoints ]


def render_refusal( results: List[ Dict[ str, Any ] ], context: str = "" ) -> str:
    """
    Render the refusal an operator reads at second one instead of hour three.

    Ensures:
        - names each dead endpoint AND what it did, first, because that is the action
        - names the live ones too: "3001 is up" is what tells the reader the box is
          half-alive rather than off, which is the state that fooled everyone
    """
    dead  = [ r for r in results if not r[ "alive" ] ]
    alive = [ r for r in results if r[ "alive" ] ]
    lines = [ f"MODEL SERVER NOT AVAILABLE — refusing to start{ ' ' + context if context else '' }.",
              "",
              "  DID NOT ANSWER:" ]
    lines += [ f"    · {r[ 'endpoint' ]} — {r[ 'detail' ]}" for r in dead ]
    if alive:
        lines += [ "", "  answered:" ]
        lines += [ f"    · {r[ 'endpoint' ]} — {r[ 'detail' ]}" for r in alive ]
        lines += [ "",
                   "  Some ports answered and some did not. A half-alive box reads as alive to any",
                   "  check that probes one port, which is how the last outage stayed invisible until",
                   "  a three-hour job died on it." ]
    lines += [ "",
               "  Bring the endpoint above back up and re-run. Nothing was measured, so no result",
               "  is missing and no prior number is falsified." ]
    return "\n".join( lines )


def require_live( endpoints: Optional[ List[ str ] ] = None, config_mgr = None,
                  timeout_s: float = DEFAULT_TIMEOUT_S, context: str = "",
                  url_opener: Optional[ Callable ] = None ) -> List[ Dict[ str, Any ] ]:
    """
    Refuse the run unless EVERY endpoint answered.

    Requires:
        - either an explicit `endpoints` list, or a config_mgr to discover them from

    Ensures:
        - returns the full probe report when every endpoint answered, so a caller can log
          WHICH tree of models it measured against
        - raises ModelServerUnavailable naming every endpoint that did not answer, and
          what it did, when any did not
        - raises ModelServerUnavailable when there is nothing to probe: an empty endpoint
          list means the discovery found nothing, and silently proceeding would be the
          same failure wearing a different hat
    """
    if endpoints is None:
        if config_mgr is None:
            raise ValueError( "require_live needs either endpoints or a config_mgr to discover them from" )
        endpoints = discover_vllm_endpoints( config_mgr )
    if not endpoints:
        raise ModelServerUnavailable(
            "no model-server endpoints to probe — nothing in the configuration names a "
            "vllm:// endpoint, so a run cannot be shown to have a live dependency at all."
        )
    results = probe_endpoints( endpoints, timeout_s=timeout_s, url_opener=url_opener )
    if any( not r[ "alive" ] for r in results ):
        raise ModelServerUnavailable( render_refusal( results, context=context ) )
    return results
