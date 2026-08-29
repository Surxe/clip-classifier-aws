"""Lambda handler: classify a gaming-clip description against clip-db's tag vocabulary.

Loads the controlled vocabulary once at cold start, then classifies each request via
Bedrock (Claude, constrained to the schema). Accepts either a direct invoke payload
({"description": ..., "game": ...}) or an API Gateway proxy event (JSON string in `body`),
which is how the deployed `POST /classify` HTTP API endpoint invokes it.
"""
import functools
import json
from pathlib import Path

import boto3

from classify import bedrock_runner, llm_classify
from tags import load_vocab

REGION = "us-east-1"
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

# Loaded once per container (cold start), reused across warm invocations.
VOCAB = load_vocab(Path(__file__).parent / "tags.json")
_bedrock = boto3.client("bedrock-runtime", region_name=REGION)
_runner = functools.partial(bedrock_runner, _bedrock)


def _parse_request(event) -> dict:
    """Support both a direct invoke payload and an API Gateway proxy event."""
    body = event.get("body")
    if isinstance(body, str):        # API Gateway proxy: JSON string
        return json.loads(body or "{}")
    if isinstance(body, dict):       # some invoke paths nest under "body"
        return body
    return event                     # direct `aws lambda invoke --payload {...}`


def handler(event, context):
    req = _parse_request(event)
    description = (req.get("description") or "").strip()
    game = (req.get("game") or "").strip()

    if not description:
        return {"statusCode": 400, "body": json.dumps({"error": "missing 'description'"})}

    # Fold the game hint into the text; the vocabulary's per-game sections do the rest.
    text = f"Game: {game}. {description}" if game else description
    result = llm_classify(text, VOCAB, runner=_runner, model=MODEL_ID)

    return {
        "statusCode": 200,
        "body": json.dumps({"tags": result.tags, "proposed_tag": result.proposed_tag}),
    }
