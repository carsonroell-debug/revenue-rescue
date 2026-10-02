"""Minimal request validation against Revenue Rescue's canonical schemas.

This keeps platform adapters and REST handlers from accepting malformed inputs
that would otherwise fail deep inside the crawler. It intentionally validates
only the constraints Revenue Rescue depends on at runtime.
"""
from __future__ import annotations

from urllib.parse import urlparse

from .contracts import tool


class ValidationError(ValueError):
    pass


def validate_tool_args(tool_name: str, args: dict) -> dict:
    schema = tool(tool_name)["input_schema"]
    if not isinstance(args, dict):
        raise ValidationError("arguments must be an object")

    required = schema.get("required", [])
    missing = [name for name in required if args.get(name) in (None, "")]
    if missing:
        raise ValidationError("missing required fields: " + ", ".join(missing))

    if schema.get("additionalProperties") is False:
        allowed = set(schema.get("properties", {}))
        extras = sorted(set(args) - allowed)
        if extras:
            raise ValidationError("unexpected fields: " + ", ".join(extras))

    out = dict(args)
    for name, prop in schema.get("properties", {}).items():
        if name not in out:
            if "default" in prop:
                out[name] = prop["default"]
            continue
        value = out[name]
        ptype = prop.get("type")

        if ptype == "integer":
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{name} must be an integer") from exc
            if "minimum" in prop and value < prop["minimum"]:
                raise ValidationError(f"{name} must be >= {prop['minimum']}")
            if "maximum" in prop and value > prop["maximum"]:
                raise ValidationError(f"{name} must be <= {prop['maximum']}")
            out[name] = value

        elif ptype == "string":
            if not isinstance(value, str):
                raise ValidationError(f"{name} must be a string")
            if prop.get("minLength") and len(value.strip()) < prop["minLength"]:
                raise ValidationError(f"{name} must not be empty")
            if "enum" in prop and value not in prop["enum"]:
                raise ValidationError(f"{name} must be one of: {', '.join(prop['enum'])}")
            if prop.get("format") == "uri":
                parsed = urlparse(value)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ValidationError(f"{name} must be a public http(s) URL")

    return out
