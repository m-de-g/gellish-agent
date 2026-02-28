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
        return True, []
    schema = _load_schema()
    validator = Draft7Validator(schema)
    errors = [
        "{}: {}".format("/".join(map(str, error.path)), error.message)
        for error in validator.iter_errors(ir_obj)
    ]
    return (len(errors) == 0, errors)
