from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft7Validator
except ImportError:  # pragma: no cover - fallback for environments without jsonschema
    Draft7Validator = None


@lru_cache(maxsize=1)
def _load_schema() -> dict[str, Any]:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "ir.schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"IR schema not found at {schema_path}")
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_ir(ir_obj: dict[str, Any]) -> tuple[bool, list[str]]:
    if Draft7Validator is None:
        errors: list[str] = []
        if not isinstance(ir_obj, dict):
            return False, ["root: must be an object"]
        required = ("sentence_id", "text", "entities", "relations")
        for field in required:
            if field not in ir_obj:
                errors.append(f"{field}: is required")
        if "sentence_id" in ir_obj and not isinstance(ir_obj["sentence_id"], str):
            errors.append("sentence_id: must be a string")
        if "text" in ir_obj and not isinstance(ir_obj["text"], str):
            errors.append("text: must be a string")
        if "entities" in ir_obj and not isinstance(ir_obj["entities"], list):
            errors.append("entities: must be an array")
        if "relations" in ir_obj and not isinstance(ir_obj["relations"], list):
            errors.append("relations: must be an array")
        return (len(errors) == 0, errors)
    schema = _load_schema()
    validator = Draft7Validator(schema)
    errors = [
        "{}: {}".format("/".join(map(str, error.path)), error.message)
        for error in validator.iter_errors(ir_obj)
    ]
    return (len(errors) == 0, errors)
