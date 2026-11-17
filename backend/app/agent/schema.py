"""Turn a Pydantic model into a tool input schema the API accepts with `strict: true`.

Strict tool schemas need every property listed in `required`, `additionalProperties: false`,
and only a subset of JSON Schema. Optional fields stay optional by allowing null.
"""

from typing import Any

from pydantic import BaseModel

_KEEP = {"type", "properties", "required", "enum", "anyOf", "items", "description", "format"}


def _clean(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_clean(n, defs) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:  # inline nested models and enums
        return _clean(defs[node["$ref"].split("/")[-1]], defs)
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "properties":
            out[key] = {name: _clean(prop, defs) for name, prop in value.items()}
        elif key in _KEEP:
            out[key] = _clean(value, defs)
    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"])
        out["additionalProperties"] = False
    return out


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    return _clean(raw, raw.get("$defs", {}))
