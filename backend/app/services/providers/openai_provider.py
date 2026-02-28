from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .base import IRProvider

DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
ALLOWED_RELATIONS = (
    "rel:is_a",
    "rel:has_part",
    "rel:part_of",
    "rel:located_in",
    "rel:located_on",
    "rel:causes",
    "rel:used_for",
    "rel:has_property",
    "rel:has_value",
    "rel:has_unit",
    "rel:has_role",
    "rel:has_name",
    "rel:has_alias",
    "rel:asserted_by",
    "rel:according_to",
)


def _load_ir_schema() -> dict[str, Any]:
    schema_path = Path(__file__).resolve().parents[3] / "schemas" / "ir.schema.json"
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class OpenAIProvider(IRProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> None:
        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError("OPENAI_API_KEY is required when provider='openai'.")

        self._api_key = resolved_key
        self.model = model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        self.temperature = temperature
        self.seed = seed
        self._schema = _load_ir_schema()
        self._client = None

    def generate_ir(self, sentence_text: str, context: dict) -> dict:
        system_prompt = (
            "You extract sentence-level semantic IR as strict JSON.\n"
            "Return exactly one JSON object matching the provided schema.\n"
            "Constraints:\n"
            "- Keep sentence_id and text aligned with input.\n"
            "- relation_uid must be one of: "
            + ", ".join(ALLOWED_RELATIONS)
            + ".\n"
            "- For unknown concepts, use provisional:* UIDs.\n"
            "- Include needs_review=true on uncertain entities or relations.\n"
            "- Confidence must be numeric in [0,1].\n"
            "- Do not return markdown or commentary."
        )
        user_prompt = self._build_user_prompt(sentence_text, context)

        try:
            return self._generate_with_schema(system_prompt, user_prompt)
        except Exception:
            return self._generate_with_json_text(system_prompt, user_prompt)

    def _build_user_prompt(self, sentence_text: str, context: dict) -> str:
        document_id = context.get("document_id")
        sentence_id = context.get("sentence_id")
        retry_errors = context.get("validation_errors") or []
        retry_attempt = int(context.get("retry_attempt") or 0)
        prompt_lines = [
            "Generate IR for this sentence.",
            f"document_id: {document_id}",
            f"sentence_id: {sentence_id}",
            f"sentence_text: {sentence_text}",
        ]
        if retry_attempt > 0 and retry_errors:
            prompt_lines.append("Previous output failed schema validation.")
            prompt_lines.append("Fix these errors:")
            prompt_lines.extend(f"- {item}" for item in retry_errors)
        return "\n".join(prompt_lines)

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is required for provider='openai'.") from exc
        self._client = OpenAI(api_key=self._api_key)
        return self._client

    def _generate_with_schema(self, system_prompt: str, user_prompt: str) -> dict:
        client = self._get_client()
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "gellish_ir",
                    "schema": self._schema,
                }
            },
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.seed is not None:
            payload["seed"] = self.seed

        response = client.responses.create(**payload)
        parsed = getattr(response, "output_parsed", None)
        if isinstance(parsed, dict):
            return parsed
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return _extract_json_object(output_text)
        raise ValueError("OpenAI response did not contain parseable JSON output.")

    def _generate_with_json_text(self, system_prompt: str, user_prompt: str) -> dict:
        client = self._get_client()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.seed is not None:
            payload["seed"] = self.seed

        completion = client.chat.completions.create(**payload)
        content = completion.choices[0].message.content or ""
        return _extract_json_object(content)


def _extract_json_object(text: str) -> dict:
    stripped = text.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output.")

    in_string = False
    escaped = False
    depth = 0
    end = -1
    for index, char in enumerate(stripped[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end == -1:
        raise ValueError("Unbalanced JSON object in model output.")

    candidate = stripped[start:end]
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("Expected top-level JSON object.")
    return parsed
