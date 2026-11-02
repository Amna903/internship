"""One validator for every structured model output (Week 5 Step 5).

The same JSON schemas are sent to Ollama (its `format` option constrains the reply) and checked here, because
a constrained reply can still be empty, cut off at the output-token limit, or wrong. `strict()` derives the
server-side schema from the one sent to the model: no extra keys anywhere, plus the server's size limits. So
the schema the model sees stays exactly as it was, and the server's check can only be tighter.

Only the JSON Schema keywords these schemas use are supported; an unknown keyword is a programming error and
raises, rather than being silently ignored.
"""

import copy
import math
import re

TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float)}
KNOWN = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "items",
    "maxLength",
    "minLength",
    "maxItems",
    "pattern",
    "enum",
    "minimum",
    "maximum",
    "description",
}


class SchemaError(ValueError):
    """The data broke the schema. The message names the path, never the value (it may be model output)."""


def validate(schema: dict, data, path: str = "$") -> None:
    unknown = set(schema) - KNOWN
    if unknown:
        raise TypeError(f"unsupported schema keyword(s): {sorted(unknown)}")
    kind = schema.get("type")
    if kind:
        kinds = kind if isinstance(kind, list) else [kind]  # e.g. ["number", "null"]
        if not any(_is(data, k) for k in kinds):
            raise SchemaError(f"{path} must be {' or '.join(kinds)}")
    if "enum" in schema and data not in schema["enum"]:
        raise SchemaError(f"{path} is not an allowed value")
    if isinstance(data, str):
        if len(data) > schema.get("maxLength", len(data)):
            raise SchemaError(f"{path} is too long")
        if len(data) < schema.get("minLength", 0):
            raise SchemaError(f"{path} is too short")
        if "pattern" in schema and not re.search(schema["pattern"], data):
            raise SchemaError(f"{path} has the wrong form")
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        if not math.isfinite(data):  # json.loads accepts NaN and Infinity; they would slip past min/max
            raise SchemaError(f"{path} must be a finite number")
        if "minimum" in schema and data < schema["minimum"]:
            raise SchemaError(f"{path} is below the minimum")
        if "maximum" in schema and data > schema["maximum"]:
            raise SchemaError(f"{path} is above the maximum")
    if isinstance(data, list):
        if len(data) > schema.get("maxItems", len(data)):
            raise SchemaError(f"{path} has too many items")
        for i, item in enumerate(data):
            if "items" in schema:
                validate(schema["items"], item, f"{path}[{i}]")
    if isinstance(data, dict):
        props = schema.get("properties", {})
        missing = [k for k in schema.get("required", []) if k not in data]
        if missing:
            raise SchemaError(f"{path} is missing {', '.join(missing)}")
        if schema.get("additionalProperties") is False and set(data) - set(props):
            raise SchemaError(f"{path} has unexpected keys")
        for key, sub in props.items():
            if key in data:
                validate(sub, data[key], f"{path}.{key}")


def _is(data, kind: str) -> bool:
    if kind == "null":
        return data is None
    # bool is a subclass of int in Python; JSON keeps them apart
    return isinstance(data, TYPES[kind]) and not (kind in ("integer", "number") and isinstance(data, bool))


def strict(schema: dict, limits: dict | None = None) -> dict:
    """A copy of `schema` with additionalProperties false on every object and every key required, plus
    `limits`: {"$.answer": {"maxLength": 1200}, "$.citations[]": {...}} merged in at those paths."""
    limits = limits or {}

    def walk(node: dict, path: str) -> dict:
        node = copy.deepcopy(node)
        if node.get("type") == "object":
            node["additionalProperties"] = False
            node["required"] = list(node.get("properties", {}))
            node["properties"] = {k: walk(v, f"{path}.{k}") for k, v in node.get("properties", {}).items()}
        if node.get("type") == "array" and "items" in node:
            node["items"] = walk(node["items"], f"{path}[]")
        node.update(limits.get(path, {}))
        return node

    return walk(schema, "$")
