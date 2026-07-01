import json
from typing import Any


def extract_json_object(text: str) -> dict[str, Any]:
    """
    Extract the first valid JSON object from model output.

    The prompts ask for JSON only, but this keeps the graph resilient if a model
    accidentally wraps JSON in markdown or adds short prose.
    """
    if not text:
        raise ValueError("Cannot extract JSON object from empty text")

    decoder = json.JSONDecoder()
    stripped = text.strip()

    try:
        value = decoder.decode(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    raise ValueError(f"No valid JSON object found in model output: {text[:300]}")
