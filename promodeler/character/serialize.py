"""Dataclass <-> JSON conversion and JSON Schema generation driven by type hints.

One set of dataclasses is the contract for three consumers: the Python
side (validation, generation), the committed ``schemas/*.json`` files and
the C# DTOs in the Unity project. Field ``metadata`` carries ``enum``,
``minimum``, ``maximum``, ``pattern`` and ``description`` into the schema
and into ``check_metadata`` so the same constraints are enforced at
validation time.
"""

from __future__ import annotations

import dataclasses
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

from ..core.diagnostics import ModelingError

NoneType = type(None)


# --- encoding -------------------------------------------------------------------------

def encode(value: Any) -> Any:
    """Dataclass instance (or any nested value) to plain JSON-compatible data. Field order is preserved."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: encode(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return float(value)
    raise ModelingError("serialize.type", f"Cannot serialize a value of type {type(value).__name__}.")


# --- decoding -------------------------------------------------------------------------

def decode(cls: type, data: Any, label: str = "$") -> Any:
    """Plain data to a dataclass instance. Unknown and missing fields are errors; types are checked."""
    if not isinstance(data, dict):
        raise ModelingError("recipe.type", f"{label} must be an object, got {type(data).__name__}.")
    fields = {f.name: f for f in dataclasses.fields(cls)}
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ModelingError("recipe.unknownField", f"{label} has unknown fields {unknown}.")
    hints = get_type_hints(cls)
    kwargs = {}
    for name, f in fields.items():
        if name in data:
            kwargs[name] = _decode_value(hints[name], data[name], f"{label}.{name}")
        elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
            raise ModelingError("recipe.missingField", f"{label}.{name} is required.")
    return cls(**kwargs)


def _decode_value(tp: Any, value: Any, label: str) -> Any:
    origin = get_origin(tp)
    args = get_args(tp)
    if tp is Any:
        return value
    if origin in (Union, types.UnionType):
        if value is None:
            if NoneType in args:
                return None
            raise ModelingError("recipe.type", f"{label} must not be null.")
        last: ModelingError | None = None
        for candidate in (a for a in args if a is not NoneType):
            try:
                return _decode_value(candidate, value, label)
            except ModelingError as error:
                last = error
        raise last or ModelingError("recipe.type", f"{label} has no matching type.")
    if origin is tuple:
        if not isinstance(value, (list, tuple)):
            raise ModelingError("recipe.type", f"{label} must be an array.")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode_value(args[0], v, f"{label}[{i}]") for i, v in enumerate(value))
        if len(value) != len(args):
            raise ModelingError("recipe.type", f"{label} needs {len(args)} items, got {len(value)}.")
        return tuple(_decode_value(a, v, f"{label}[{i}]") for i, (a, v) in enumerate(zip(args, value)))
    if origin is dict or tp is dict:
        if not isinstance(value, dict):
            raise ModelingError("recipe.type", f"{label} must be an object.")
        if len(args) == 2:
            return {str(k): _decode_value(args[1], v, f"{label}.{k}") for k, v in value.items()}
        return dict(value)
    if dataclasses.is_dataclass(tp):
        return decode(tp, value, label)
    if tp is bool:
        if isinstance(value, bool):
            return value
    elif tp is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    elif tp is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    elif tp is str:
        if isinstance(value, str):
            return value
    else:
        raise ModelingError("serialize.type", f"{label}: unsupported field type {tp!r}.")
    raise ModelingError("recipe.type", f"{label} must be {tp.__name__}, got {type(value).__name__}.")


# --- metadata constraints ------------------------------------------------------------------

def check_metadata(instance: Any, label: str = "$") -> None:
    """Enforce ``enum`` / ``minimum`` / ``maximum`` / ``pattern`` field metadata recursively."""
    import re

    for f in dataclasses.fields(instance):
        value = getattr(instance, f.name)
        meta = f.metadata
        path = f"{label}.{f.name}"
        scalars = value if isinstance(value, (list, tuple)) else (value,)
        for scalar in scalars:
            if scalar is None or dataclasses.is_dataclass(scalar) or isinstance(scalar, (dict, list, tuple)):
                continue
            if "enum" in meta and scalar not in meta["enum"]:
                raise ModelingError("recipe.enum", f"{path} must be one of {list(meta['enum'])}, got {scalar!r}.")
            if "minimum" in meta and isinstance(scalar, (int, float)) and scalar < meta["minimum"]:
                raise ModelingError("recipe.range", f"{path} must be >= {meta['minimum']}, got {scalar!r}.")
            if "maximum" in meta and isinstance(scalar, (int, float)) and scalar > meta["maximum"]:
                raise ModelingError("recipe.range", f"{path} must be <= {meta['maximum']}, got {scalar!r}.")
            if "pattern" in meta and isinstance(scalar, str) and not re.fullmatch(meta["pattern"], scalar):
                raise ModelingError("recipe.pattern", f"{path} does not match {meta['pattern']}: {scalar!r}.")
        for i, item in enumerate(scalars):
            if dataclasses.is_dataclass(item) and not isinstance(item, type):
                check_metadata(item, f"{path}[{i}]" if isinstance(value, (list, tuple)) else path)


# --- JSON Schema ---------------------------------------------------------------------------

def schema(cls: type, schema_id: str, title: str, description: str = "") -> dict:
    """JSON Schema (draft 2020-12) for a dataclass, with nested dataclasses in ``$defs``."""
    defs: dict[str, dict] = {}
    root = _schema_type(cls, defs, {})
    out: dict = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": schema_id, "title": title}
    if description:
        out["description"] = description
    ref = root.pop("$ref")
    out.update(defs.pop(ref.rsplit("/", 1)[1]))
    if defs:
        out["$defs"] = dict(sorted(defs.items()))
    return out


def _schema_type(tp: Any, defs: dict, meta: Any) -> dict:
    origin = get_origin(tp)
    args = get_args(tp)
    if tp is Any:
        return {}
    if origin in (Union, types.UnionType):
        nullable = NoneType in args
        branches = [_schema_type(a, defs, meta) for a in args if a is not NoneType]
        inner = branches[0] if len(branches) == 1 else {"anyOf": branches}
        if not nullable:
            return inner
        if "type" in inner and isinstance(inner["type"], str) and set(inner) <= {"type", "enum", "minimum", "maximum", "pattern", "items", "prefixItems", "minItems", "maxItems"}:
            out = dict(inner)
            out["type"] = [inner["type"], "null"]
            if "enum" in out:
                out["enum"] = list(out["enum"]) + [None]
            return out
        return {"anyOf": [inner, {"type": "null"}]}
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return {"type": "array", "items": _schema_type(args[0], defs, meta)}
        return {"type": "array", "prefixItems": [_schema_type(a, defs, meta) for a in args], "minItems": len(args), "maxItems": len(args)}
    if origin is dict or tp is dict:
        out: dict = {"type": "object"}
        if len(args) == 2:
            out["additionalProperties"] = _schema_type(args[1], defs, meta)
        return out
    if dataclasses.is_dataclass(tp):
        name = tp.__name__
        if name not in defs:
            defs[name] = {}  # placeholder against recursion
            hints = get_type_hints(tp)
            properties = {}
            required = []
            for f in dataclasses.fields(tp):
                prop = _schema_type(hints[f.name], defs, f.metadata)
                prop = _apply_metadata(prop, f.metadata)
                if f.default is not dataclasses.MISSING:
                    prop["default"] = encode(f.default)
                elif f.default_factory is dataclasses.MISSING:
                    required.append(f.name)
                properties[f.name] = prop
            entry: dict = {"type": "object", "properties": properties, "additionalProperties": False}
            if tp.__doc__:
                entry["description"] = " ".join(tp.__doc__.split())
            if required:
                entry["required"] = required
            defs[name] = entry
        return {"$ref": f"#/$defs/{name}"}
    primitive = {bool: "boolean", int: "integer", float: "number", str: "string"}.get(tp)
    if primitive is None:
        raise ModelingError("serialize.type", f"Unsupported type in schema: {tp!r}.")
    return {"type": primitive}


def _apply_metadata(prop: dict, meta: Any) -> dict:
    out = dict(prop)
    target = out
    if "anyOf" in out and meta:
        target = out["anyOf"][0]
    for key in ("minimum", "maximum", "pattern", "description"):
        if key in meta:
            target[key] = meta[key]
    if "enum" in meta:
        values = list(meta["enum"])
        if isinstance(target.get("type"), list) and "null" in target["type"]:
            values = values + [None]
        target["enum"] = values
    if "anyOf" in out and meta and target is not out:
        out["anyOf"][0] = target
    return out
