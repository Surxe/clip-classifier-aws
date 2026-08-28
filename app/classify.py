"""Constrained LLM classification on Amazon Bedrock.

Ported from clip-db's clip_core/classify.py. The system prompt and the
JSON-schema-constrained output (a `tags` enum over the controlled vocabulary plus a
nullable `proposed_tag`) are unchanged. The only swap is the runner: instead of shelling
out to the `claude` CLI, this calls Bedrock's Messages API and constrains the output by
forcing a single tool call whose `input_schema` *is* the classification schema - the
reliable way to get schema-valid JSON from any Claude model on Bedrock.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from tags import TagVocab

SYSTEM = (
    "You map a short free-text description of a gaming clip onto a fixed controlled "
    "vocabulary of tags. Choose only tags from the provided list that genuinely apply "
    "(use meaning, not string overlap: '1v4 retake' -> clutch, 'whiffed everything' -> fail). "
    "The vocabulary is organised into generic tags and per-game sections; when a clip is "
    "from a game, tag it with that game's name plus any specific weapons/modules/abilities "
    "shown. Group headings (weapons, modules, abilities) are organisation only, not tags. "
    "Do not invent tags. Only if nothing in the vocabulary fits, set proposed_tag to a single "
    "concise new tag; otherwise proposed_tag is null."
)


@dataclass
class Classification:
    tags: list[str]
    proposed_tag: str | None = None


def build_schema(vocab: TagVocab) -> dict:
    return {
        "type": "object",
        "properties": {
            "tags": {
                "type": "array",
                "items": {"type": "string", "enum": vocab.as_list()},
            },
            "proposed_tag": {
                "type": ["string", "null"],
                "description": "A single new tag, only if nothing in the vocabulary fits; else null.",
            },
        },
        "required": ["tags", "proposed_tag"],
        "additionalProperties": False,
    }


def _build_system(vocab: TagVocab) -> str:
    return f"{SYSTEM}\n\n# Vocabulary\n{vocab.to_markdown()}"


def bedrock_runner(bedrock_client, *, prompt: str, system: str, schema: dict, model: str) -> dict:
    """Constrain Claude's output by forcing one tool call whose input schema is `schema`.

    Returns the tool's parsed `input` dict (already schema-valid), matching the
    `{tags, proposed_tag}` shape the caller expects.
    """
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [
            {
                "name": "classify",
                "description": "Return the tags for the described clip.",
                "input_schema": schema,
            }
        ],
        "tool_choice": {"type": "tool", "name": "classify"},
    }
    resp = bedrock_client.invoke_model(modelId=model, body=json.dumps(body))
    payload = json.loads(resp["body"].read())
    for block in payload.get("content", []):
        if block.get("type") == "tool_use":
            return block["input"]
    raise RuntimeError(f"Bedrock returned no tool_use block: {payload}")


def llm_classify(description: str, vocab: TagVocab, *, runner, model: str) -> Classification:
    """Classify one description. `runner(*, prompt, system, schema, model) -> dict`.

    `runner` is injected (a Bedrock-backed closure in the Lambda; a stub in tests),
    preserving the seam the original clip-db classifier used.
    """
    data = runner(
        prompt=f"Description: {description}",
        system=_build_system(vocab),
        schema=build_schema(vocab),
        model=model,
    )
    return Classification(
        tags=data.get("tags", []),
        proposed_tag=data.get("proposed_tag"),
    )
