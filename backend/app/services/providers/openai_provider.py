from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .base import IRProvider, ProviderError, ProviderResult, ProviderUsage

DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"
DEFAULT_OPENAI_TEMPERATURE = 0.1
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
        self.temperature = (
            temperature
            if temperature is not None
            else float(os.getenv("OPENAI_TEMPERATURE") or DEFAULT_OPENAI_TEMPERATURE)
        )
        self.seed = seed
        self._schema = _load_ir_schema()
        self._client = None

    def generate_ir(self, sentence_text: str, context: dict) -> ProviderResult:
        system_prompt = (
            "You extract sentence-level semantic IR as strict JSON.\n"
            "Return exactly one JSON object.\n"
            "Top-level keys must be exactly: sentence_id, text, entities, relations.\n"
            "Required top-level keys entities and relations must always be present as arrays.\n"
            "Do not include any other top-level keys.\n"
            "Use this JSON skeleton:\n"
            '{\n  "sentence_id": "<string>",\n  "text": "<string>",\n  "entities": [],\n  "relations": []\n}\n'
            "Constraints:\n"
            "- Keep sentence_id and text aligned with input.\n"
            "- Emit entities as a list under the top-level key entities.\n"
            "- Emit relations as a list under the top-level key relations.\n"
            "- Do not use placeholder UIDs like provisional:subject or provisional:object.\n"
            "- Every relation must include a non-null subject_uid.\n"
            "- Every relation must include exactly one of object_uid or object_literal (object_uid XOR object_literal).\n"
            "- relation_uid must be one of: "
            + ", ".join(ALLOWED_RELATIONS)
            + ".\n"
            "- For unknown concepts, use provisional:* UIDs.\n"
            "- For pattern 'X has Y', emit entities for X and Y with meaningful provisional UIDs derived from surface labels.\n"
            "- Example for 'A toaster has a lever.': entities should include provisional:toaster and provisional:lever, and relations should include rel:has_part with subject_uid=provisional:toaster and object_uid=provisional:lever.\n"
            "- Include needs_review=true on uncertain entities or relations.\n"
            "- Confidence must be numeric in [0,1].\n"
            "- Do not return markdown or commentary."
        )
        user_prompt = self._build_user_prompt(sentence_text, context)

        try:
            return self._generate_with_schema(system_prompt, user_prompt)
        except ProviderError:
            raise
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
            prompt_lines.append(
                "Return ONLY corrected JSON with required keys entities and relations."
            )
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

    def _generate_with_schema(self, system_prompt: str, user_prompt: str) -> ProviderResult:
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

        try:
            response = client.responses.create(**payload)
        except Exception as exc:
            raise self._map_openai_exception(exc) from exc
        parsed = getattr(response, "output_parsed", None)
        if isinstance(parsed, dict):
            return ProviderResult(ir=parsed, usage=_extract_responses_usage(response))
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return ProviderResult(
                ir=_extract_json_object(output_text),
                usage=_extract_responses_usage(response),
            )
        raise ValueError("OpenAI response did not contain parseable JSON output.")

    def _generate_with_json_text(self, system_prompt: str, user_prompt: str) -> ProviderResult:
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

        try:
            completion = client.chat.completions.create(**payload)
        except Exception as exc:
            raise self._map_openai_exception(exc) from exc
        content = completion.choices[0].message.content or ""
        return ProviderResult(
            ir=_extract_json_object(content),
            usage=_extract_chat_usage(completion),
        )

    def _map_openai_exception(self, exc: Exception) -> ProviderError:
        message = _sanitize_error_message(exc)
        try:
            from openai import (
                APIConnectionError,
                APIError,
                APITimeoutError,
                AuthenticationError,
                BadRequestError,
                InternalServerError,
                RateLimitError,
            )
        except ImportError:
            return ProviderError(kind="unknown", message=message, status_code=502)

        if isinstance(exc, AuthenticationError):
            return ProviderError(kind="auth", message=message, status_code=400)
        if isinstance(exc, RateLimitError):
            if "quota" in message.lower() or "insufficient_quota" in message.lower():
                return ProviderError(kind="quota", message=message, status_code=402)
            return ProviderError(kind="rate_limit", message=message, status_code=429)
        if isinstance(exc, APITimeoutError):
            return ProviderError(kind="timeout", message=message, status_code=504)
        if isinstance(exc, BadRequestError):
            return ProviderError(kind="bad_request", message=message, status_code=400)
        if isinstance(exc, APIConnectionError):
            return ProviderError(kind="server", message=message, status_code=502)
        if isinstance(exc, InternalServerError):
            return ProviderError(kind="server", message=message, status_code=502)
        if isinstance(exc, APIError):
            status_code = int(getattr(exc, "status_code", 0) or 0)
            if status_code == 402:
                return ProviderError(kind="quota", message=message, status_code=402)
            if status_code in {500, 502, 503, 504}:
                return ProviderError(kind="server", message=message, status_code=502)
            if status_code == 429:
                return ProviderError(kind="rate_limit", message=message, status_code=429)
            return ProviderError(kind="unknown", message=message, status_code=502)

        return ProviderError(kind="unknown", message=message, status_code=502)


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


def _sanitize_error_message(exc: Exception) -> str:
    raw = str(exc).strip()
    if not raw:
        return "Provider request failed."
    compact = " ".join(raw.split())
    return compact[:300]


def _extract_responses_usage(response: Any) -> ProviderUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt = _as_int(_read_field(usage, "input_tokens"))
    completion = _as_int(_read_field(usage, "output_tokens"))
    total = _as_int(_read_field(usage, "total_tokens"))
    if prompt is None and completion is None and total is None:
        return None
    return ProviderUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def _extract_chat_usage(completion: Any) -> ProviderUsage | None:
    usage = getattr(completion, "usage", None)
    if usage is None:
        return None
    prompt = _as_int(_read_field(usage, "prompt_tokens"))
    completion_tokens = _as_int(_read_field(usage, "completion_tokens"))
    total = _as_int(_read_field(usage, "total_tokens"))
    if prompt is None and completion_tokens is None and total is None:
        return None
    return ProviderUsage(prompt_tokens=prompt, completion_tokens=completion_tokens, total_tokens=total)


def _read_field(source: Any, field: str) -> Any:
    if isinstance(source, dict):
        return source.get(field)
    return getattr(source, field, None)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
