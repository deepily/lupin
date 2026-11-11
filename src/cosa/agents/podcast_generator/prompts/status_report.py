#!/usr/bin/env python3
"""
Prompts for the status_report script type of the podcast generator.

A status report walks what is done, then what is outstanding, and comments on the
tricky parts, the unresolved issues and anything that threatens completion.
"""

import json
from typing import Optional

from ..config import HostPersonality
from .script_generation import AUDIENCE_DIALOGUE_GUIDELINES


STATUS_DIGEST_SYSTEM_PROMPT = """You are a project analyst preparing a status report for podcast production.

Your task is to read a status document and list, without inventing anything:
1. What is done
2. What is outstanding
3. What was tricky
4. What is unresolved
5. What is blocked
6. The next steps

Every item is an object with two fields. "text" is one plain sentence. "source_line" is the
line from the document the item came from, copied exactly, character for character.

Output your analysis as JSON with this structure:
{
    "main_topic": "string",
    "done": [{"text": "string", "source_line": "string"}, ...],
    "outstanding": [{"text": "string", "source_line": "string"}, ...],
    "tricky": [{"text": "string", "source_line": "string"}, ...],
    "unresolved": [{"text": "string", "source_line": "string"}, ...],
    "blocked": [{"text": "string", "source_line": "string"}, ...],
    "next_steps": [{"text": "string", "source_line": "string"}, ...]
}

Use an empty list for a category the document does not mention."""


STATUS_REPORT_SYSTEM_PROMPT = """You are a podcast script writer creating a short spoken status report for a two-host show.

The two hosts have complementary roles:
- The curious host asks "where are we?" and the follow-up questions a busy listener would ask
- The expert host answers from the status digest

Walk the accomplishments first, then the outstanding items. Comment on what was completed,
the tricky parts, the unresolved issues, and anything that threatens completion.
Stay on the status. Do not teach theory or background.

SCRIPT FORMAT:
**[Host Name - Role]**: Dialogue text with pacing markers like <break time="1.0s"/> as needed.

PACING & EMPHASIS MARKERS:
Write these directly into the dialogue text. They are the only markers our voice engine renders.
- <break time="1.5s"/> - An explicit silent pause. Maximum 3.0 seconds.
- Ellipsis ( ... ) - A short, hesitant pause mid-thought.
- Dash ( - ) - A brief pause or a self-interruption.
- CAPITALIZATION of a word - Vocal emphasis on that word.

Do not use bracketed emotion tags such as [excited], [laughs], *[pause]* or *[whispers]*.
The voice engine ignores them and they are stripped.

DIALOGUE GUIDELINES:
1. Keep the conversation natural and brisk
2. Say only what the digest supports
3. Name each outstanding item and what would finish it
4. Say plainly what threatens completion
5. End with the next steps

OUTPUT FORMAT:
Return a JSON object with this structure. Inside a "text" value every double quote is
escaped with a backslash, so a pause tag is written <break time=\\"1.5s\\"/> there.
{
    "title": "Episode title",
    "segments": [
        {
            "speaker": "Host Name",
            "role": "curious|expert",
            "text": "Dialogue with <break time=\\"1.0s\\"/> pacing markers",
            "topic_reference": "which part of the status this covers"
        }
    ],
    "key_topics": ["topic1", "topic2", ...],
    "estimated_duration_minutes": number
}"""


def _clip( text: str, max_source_chars: Optional[ int ] ) -> str:
    """Clip text to the configured ceiling; None means no clip."""
    if max_source_chars is not None and len( text ) > max_source_chars: return text[ :max_source_chars ]
    return text


def _audience_block( audience: Optional[ str ], audience_context: Optional[ str ] ) -> str:
    """Build the audience guidance block shared by the status prompts."""
    block = ""
    if audience:
        guidelines = AUDIENCE_DIALOGUE_GUIDELINES.get( audience, "" )
        if guidelines: block += f"\n{guidelines}\n"
    if audience_context: block += f"\n**Additional Audience Context**: {audience_context}\n"
    return block


def get_status_analysis_prompt(
    research_content : str,
    audience         : Optional[ str ] = None,
    audience_context : Optional[ str ] = None,
    max_source_chars : Optional[ int ] = None,
) -> str:
    """
    Build the user prompt that asks for a status digest.

    Requires:
        - research_content is the status document text

    Ensures:
        - the prompt carries the whole document, clipped to max_source_chars
        - the prompt asks for JSON in the shape of STATUS_DIGEST_SYSTEM_PROMPT
    """
    return f"""Analyze this status document for a spoken status report.

List every completed item, every outstanding item, and the tricky, unresolved and blocked items.
Quote the source line for each item exactly.
{_audience_block( audience, audience_context )}
STATUS DOCUMENT:
---
{_clip( research_content, max_source_chars )}
---

Provide your digest as JSON."""


def get_status_script_prompt(
    content_analysis        : dict,
    research_content        : str,
    host_a_personality      : HostPersonality,
    host_b_personality      : HostPersonality,
    target_duration_minutes : int,
    min_exchanges           : int,
    max_exchanges           : int,
    audience                : Optional[ str ] = None,
    audience_context        : Optional[ str ] = None,
    max_source_chars        : Optional[ int ] = None,
) -> str:
    """
    Build the user prompt that asks for a status-report script.

    Requires:
        - content_analysis is a StatusDigest dumped to a dict
        - the three numbers come from the resolved config

    Ensures:
        - the prompt states the duration and exchange range it was given
        - the prompt carries no analogy step and no research template
    """
    return f"""Create a spoken status report script from the following digest and source document.

TARGET SPECIFICATIONS:
- Duration: approximately {target_duration_minutes} minutes
- Exchanges: {min_exchanges}-{max_exchanges} dialogue turns
- Format: Natural conversation between two hosts
{_audience_block( audience, audience_context )}
HOST A (CURIOUS ROLE):
{host_a_personality.to_prompt_description()}

HOST B (EXPERT ROLE):
{host_b_personality.to_prompt_description()}

STATUS DIGEST:
{json.dumps( content_analysis, indent=2 )}

SOURCE DOCUMENT (for reference):
---
{_clip( research_content, max_source_chars )}
---

INSTRUCTIONS:
1. Open by asking where things stand
2. Walk every done item from the digest
3. Walk every outstanding item and say what would finish it
4. Comment on the tricky, unresolved and blocked items
5. Say what threatens completion
6. Close with the next steps

Generate the complete script as JSON."""
